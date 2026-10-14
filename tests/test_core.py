"""Fast unit tests; none require Detectron2, CUDA, a camera, or real datasets."""

import json
import io
import struct
import sys
import tempfile
import threading
import unittest
import zlib
from contextlib import redirect_stderr
from types import SimpleNamespace
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch

from src.core.contact_logic import advance_track_contact, analyze_predictions
from src.core.geometry import (box_roi_overlap, clip_box, intersection_over_box_area_polygon,
                               normalized_roi_to_pixels, point_in_polygon, validate_polygon)
from src.services.camera import CaptureError, atomic_write_bytes, fetch_jpeg
from src.services.event_store import EventStore
from src.services.sensors import MockSensor, UnconfiguredSensor
from src.services.history import get_history
from src.realtime_worker import _analyze_frame, run as run_worker, update_tracks
from src.utils.config import DEFAULTS, load_settings, save_settings, validate_settings
from src.datasets.tools import read_image_dimensions, validate_dataset

THRESHOLDS = {"no_contact": 0.5, "self_contact": 0.5,
              "other_person_contact": 0.4, "object_contact": 0.6}


def png_bytes(width, height):
    def chunk(kind, data):
        return (struct.pack(">I", len(data)) + kind + data
                + struct.pack(">I", zlib.crc32(kind + data) & 0xffffffff))
    pixels = b"".join(b"\x00" + b"\x20\x40\x60\xff" * width for unused in range(height))
    return (b"\x89PNG\r\n\x1a\n"
            + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(pixels)) + chunk(b"IEND", b""))


class GeometryTests(unittest.TestCase):
    def test_roi_mapping_clipping_and_overlap(self):
        self.assertEqual(normalized_roi_to_pixels([0.1, 0.2, 0.9, 0.8], 100, 50),
                         (10.0, 10.0, 90.0, 40.0))
        self.assertEqual(clip_box([-4, 5, 20, 80], 100, 50), (0.0, 5.0, 20.0, 50.0))
        self.assertAlmostEqual(box_roi_overlap([0, 0, 10, 10], [5, 0, 20, 10]), 0.5)
        self.assertEqual(box_roi_overlap([0, 0, 10, 10], [10, 0, 20, 10]), 0.0)

    def test_invalid_or_empty_geometry(self):
        with self.assertRaises(ValueError):
            normalized_roi_to_pixels([0.8, 0.2, 0.1, 0.9], 100, 100)
        self.assertIsNone(clip_box([2, 2, 2, 4], 100, 100))

    def test_convex_polygon_overlap_and_boundary(self):
        diamond = [(5, 0), (10, 5), (5, 10), (0, 5)]
        self.assertAlmostEqual(intersection_over_box_area_polygon(
            [0, 0, 10, 10], diamond), 0.5)
        self.assertEqual(intersection_over_box_area_polygon([0, 0, 2, 2], diamond), 0.0)
        self.assertTrue(point_in_polygon((5, 5), diamond))
        self.assertTrue(point_in_polygon((5, 0), diamond))
        self.assertFalse(point_in_polygon((0, 0), diamond))

    def test_polygon_rejects_nonconvex_or_out_of_range_roi(self):
        with self.assertRaises(ValueError):
            validate_polygon([(0, 0), (1, 0), (0.4, 0.3), (0, 1)], normalized=True)
        with self.assertRaises(ValueError):
            validate_polygon([(-0.1, 0), (1, 0), (1, 1), (0, 1)], normalized=True)


class ContactLogicTests(unittest.TestCase):
    def test_no_hands_and_no_contact_have_distinct_states(self):
        no_hands = analyze_predictions([], [], [], [0, 0, 10, 10], THRESHOLDS)
        no_contact = analyze_predictions([[1, 1, 9, 9]], [0.95],
                                         [[0.8, 0.1, 0.1, 0.1]],
                                         [0, 0, 10, 10], THRESHOLDS)
        self.assertEqual(no_hands["condition"], "NO_HANDS")
        self.assertEqual(no_contact["condition"], "HANDS_NO_CONTACT")
        self.assertEqual(no_contact["status"], "OK")

    def test_contact_suspicion_requires_roi_overlap(self):
        scores = [[0.05, 0.1, 0.1, 0.88]]
        outside = analyze_predictions([[20, 20, 30, 30]], [0.9], scores,
                                      [0, 0, 10, 10], THRESHOLDS)
        inside = analyze_predictions([[5, 5, 15, 15]], [0.9], scores,
                                     [0, 0, 10, 10], THRESHOLDS)
        self.assertEqual(outside["condition"], "CONTACT_CANDIDATE_OUTSIDE_ROI")
        self.assertEqual(inside["event_kind"], "AI_CONTACT_SUSPECTED_IN_ROI")
        self.assertIn("verify", inside["message"])

    def test_polygon_roi_rejects_bbox_only_corner_overlap(self):
        diamond = [(5, 0), (10, 5), (5, 10), (0, 5)]
        scores = [[0.05, 0.1, 0.1, 0.95]]
        corner = analyze_predictions([[0, 0, 2, 2]], [0.9], scores,
                                     [0, 0, 10, 10], THRESHOLDS, 0.3,
                                     roi_polygon=diamond)
        center = analyze_predictions([[4, 4, 6, 6]], [0.9], scores,
                                     [0, 0, 10, 10], THRESHOLDS, 0.3,
                                     roi_polygon=diamond)
        self.assertEqual(corner["condition"], "CONTACT_CANDIDATE_OUTSIDE_ROI")
        self.assertEqual(center["event_kind"], "AI_CONTACT_SUSPECTED_IN_ROI")

    def test_misaligned_and_invalid_scores_raise(self):
        with self.assertRaises(ValueError):
            analyze_predictions([[0, 0, 1, 1]], [], [], [0, 0, 1, 1], THRESHOLDS)
        with self.assertRaises(ValueError):
            analyze_predictions([[0, 0, 1, 1]], [0.9], [[0, 0, 0, 2]],
                                [0, 0, 1, 1], THRESHOLDS)


class ConfigTests(unittest.TestCase):
    def test_config_defaults_and_validation(self):
        defaults = validate_settings(DEFAULTS)
        self.assertFalse(defaults["roi"]["enabled"])
        self.assertEqual(defaults["roi"]["shape"], "rectangle")
        bad = json.loads(json.dumps(DEFAULTS))
        bad["roi"]["coordinates"] = [0.9, 0.1, 0.2, 0.8]
        with self.assertRaises(ValueError):
            validate_settings(bad)

    def test_polygon_roi_config_is_normalized_and_derives_bbox(self):
        config = json.loads(json.dumps(DEFAULTS))
        config["roi"].update({"shape": "polygon", "points": [
            [0.2, 0.1], [0.8, 0.2], [0.7, 0.9], [0.3, 0.8]]})
        roi = validate_settings(config)["roi"]
        self.assertEqual(roi["coordinates"], [0.2, 0.1, 0.8, 0.9])
        self.assertEqual(roi["points"][0], [0.2, 0.1])
        bad = json.loads(json.dumps(config))
        bad["roi"]["points"][0][0] = -0.1
        with self.assertRaises(ValueError):
            validate_settings(bad)

    def test_temporal_distance_rejects_nonfinite_value(self):
        settings = validate_settings(DEFAULTS)
        settings["alert"]["track_match_distance_normalized"] = float("nan")
        with self.assertRaises(ValueError):
            validate_settings(settings)

    def test_atomic_settings_round_trip(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "pbl4.json"
            save_settings(DEFAULTS, path)
            self.assertEqual(load_settings(path)["thresholds"]["object_contact"], 0.15)
            self.assertEqual(list(Path(directory).glob("*.tmp")), [])

    def test_runtime_camera_url_is_not_written_into_config(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "pbl4.json"
            with patch.dict("os.environ", {"PBL4_CAMERA_URL": "http://192.0.2.4/capture"}):
                save_settings(DEFAULTS, path)
            saved = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(saved["camera"]["url"], "")
            self.assertNotIn("192.0.2.4", path.read_text(encoding="utf-8"))


class CameraTests(unittest.TestCase):
    def test_atomic_snapshot_replace(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "capture.jpg"
            atomic_write_bytes(target, b"\xff\xd8\xfffirst\xff\xd9")
            atomic_write_bytes(target, b"\xff\xd8\xffsecond\xff\xd9")
            self.assertEqual(target.read_bytes(), b"\xff\xd8\xffsecond\xff\xd9")
            self.assertEqual(list(Path(directory).glob("*.tmp")), [])

    def test_invalid_camera_url_does_not_open_network(self):
        with self.assertRaises(CaptureError):
            fetch_jpeg("file:///invalid.jpg")

    def test_camera_http_jpeg_and_truncated_response(self):
        payload = b"\xff\xd8\xffcamera-test\xff\xd9"

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                body = payload if self.path == "/capture" else b"\xff\xd8\xffpartial"
                self.send_response(200)
                self.send_header("Content-Type", "image/jpeg")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, format_string, *args):
                pass

        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            origin = "http://127.0.0.1:{}".format(server.server_port)
            self.assertEqual(fetch_jpeg(origin + "/capture"), payload)
            with self.assertRaises(CaptureError):
                fetch_jpeg(origin + "/truncated")
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)


class EventStoreTests(unittest.TestCase):
    def test_history_cooldown_and_status_persist(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "events.sqlite3"
            store = EventStore(path)
            store.set_status("CAMERA_DISCONNECTED", mode="camera", message="timeout")
            first = store.record_event("suspected", {"oc": 0.8}, cooldown_seconds=30,
                                       timestamp=100)
            self.assertIsNotNone(first)
            self.assertIsNone(store.record_event("suspected", {"oc": 0.9},
                                                 cooldown_seconds=30, timestamp=110))
            second = store.record_event("suspected", {"oc": 0.7}, cooldown_seconds=30,
                                        timestamp=140)
            self.assertIsNotNone(second)
            reopened = EventStore(path)
            self.assertEqual(reopened.get_status()["status"], "CAMERA_DISCONNECTED")
            self.assertEqual(len(reopened.list_events()), 2)

    def test_evidence_path_is_attached_without_replacing_event(self):
        with tempfile.TemporaryDirectory() as directory:
            store = EventStore(Path(directory) / "events.sqlite3")
            event_id = store.record_event("suspected", {"oc": 0.8})
            evidence = Path(directory) / "evidence.jpg"
            self.assertTrue(store.set_event_evidence(event_id, evidence))
            self.assertEqual(store.list_events()[0]["evidence_path"], str(evidence))

    def test_history_filters_by_type_and_processing_state(self):
        with tempfile.TemporaryDirectory() as directory:
            with patch.dict("os.environ", {"PBL4_EVENT_DB": str(Path(directory) / "events.sqlite3")}):
                store = EventStore(Path(directory) / "events.sqlite3")
                store.record_event("AI_CONTACT_SUSPECTED_IN_ROI", {"event_status": "unverified"})
                store.record_event("CAMERA_RECOVERED", {"message": "reconnected"})
                selected = get_history(20, event_type="AI_CONTACT_SUSPECTED_IN_ROI", status="OPEN")
            self.assertEqual(len(selected), 1)
            self.assertEqual(selected[0]["status"], "unverified")

    def test_worker_records_startup_error_instead_of_claiming_ok(self):
        with tempfile.TemporaryDirectory() as directory:
            database = Path(directory) / "startup.sqlite3"
            args = SimpleNamespace(mode="image", database=str(database), config_json=None)
            output = io.StringIO()
            with patch.dict(sys.modules, {"cv2": None}), redirect_stderr(output):
                result = run_worker(args)
            self.assertEqual(result, 2)
            self.assertIn("OpenCV unavailable", output.getvalue())
            status = EventStore(database).get_status()
            self.assertEqual(status["status"], "ERROR")
            self.assertIn("OpenCV unavailable", status["message"])

    def test_worker_reports_unconfigured_camera_as_disconnected(self):
        with tempfile.TemporaryDirectory() as directory:
            database = Path(directory) / "camera.sqlite3"
            args = SimpleNamespace(
                mode="camera", database=str(database), config_json=None,
                config=None, weights=None, second_stream_config=None,
                second_stream_weights=None, device=None, camera_url=None,
                frame_file=str(Path(directory) / "frame.jpg"),
                poll_interval=None, once=True,
            )
            with patch.dict(sys.modules, {"cv2": SimpleNamespace()}):
                with patch("src.realtime_worker._load_detector", return_value=object()):
                    result = run_worker(args)
            self.assertEqual(result, 1)
            status = EventStore(database).get_status()
            self.assertEqual(status["status"], "CAMERA_DISCONNECTED")
            self.assertIn("URL is not configured", status["message"])


class WorkerFrameTests(unittest.TestCase):
    def test_polygon_roi_is_drawn_and_reported(self):
        class Frame:
            shape = (100, 100, 3)

            def copy(self):
                return Frame()

        class Points:
            def reshape(self, unused_shape):
                return self

        class Numpy:
            @staticmethod
            def asarray(values, dtype=None):
                return Points()

        class CV2:
            FONT_HERSHEY_SIMPLEX = 0
            LINE_AA = 0

            def __init__(self):
                self.polygons = []

            def polylines(self, image, polygons, closed, color, thickness):
                self.polygons.append((polygons, closed))

            @staticmethod
            def rectangle(*args, **kwargs):
                pass

            @staticmethod
            def putText(*args, **kwargs):
                pass

            @staticmethod
            def imencode(*args, **kwargs):
                return True, memoryview(b"\xff\xd8\xffframe\xff\xd9")

        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            settings = validate_settings(DEFAULTS)
            points = [[0.2, 0.1], [0.8, 0.2], [0.7, 0.9], [0.3, 0.8]]
            settings["roi"].update({"enabled": True, "shape": "polygon", "points": points})
            settings["paths"]["latest_frame"] = str(base / "latest.jpg")
            settings["paths"]["evidence_dir"] = str(base / "evidence")
            store, cv2 = EventStore(base / "events.sqlite3"), CV2()
            with patch.dict(sys.modules, {"numpy": Numpy()}):
                with patch("src.realtime_worker._get_predictions", return_value=([], [], [])):
                    _analyze_frame(cv2, store, object(), Frame(), settings, "test", {}, {}, 0)
            report = store.get_status()["report"]
            self.assertEqual(report["roi_shape"], "polygon")
            self.assertEqual(report["roi_polygon"], [[20.0, 10.0], [80.0, 20.0],
                                                      [70.0, 90.0], [30.0, 80.0]])
            self.assertEqual(len(cv2.polygons), 1)
            self.assertTrue(cv2.polygons[0][1])

    def test_temporal_alert_creates_one_event_and_evidence(self):
        class Frame:
            shape = (100, 100, 3)

            def copy(self):
                return Frame()

        class CV2:
            FONT_HERSHEY_SIMPLEX = 0
            LINE_AA = 0

            @staticmethod
            def rectangle(*args, **kwargs):
                pass

            @staticmethod
            def putText(*args, **kwargs):
                pass

            @staticmethod
            def imencode(*args, **kwargs):
                return True, memoryview(b"\xff\xd8\xffsynthetic-frame\xff\xd9")

        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            settings = validate_settings(DEFAULTS)
            settings["roi"].update({
                "enabled": True, "coordinates": [40, 40, 60, 60],
                "normalized": False, "minimum_bbox_overlap": 0.3,
            })
            settings["paths"]["latest_frame"] = str(base / "latest.jpg")
            settings["paths"]["evidence_dir"] = str(base / "evidence")
            store = EventStore(base / "events.sqlite3")
            sequence = [
                ([20, 45, 30, 55], [0.05, 0.05, 0.05, 0.95]),
                ([42, 45, 52, 55], [0.05, 0.05, 0.05, 0.95]),
                ([42, 45, 52, 55], [0.05, 0.05, 0.05, 0.95]),
                ([42, 45, 52, 55], [0.05, 0.05, 0.05, 0.95]),
                ([42, 45, 52, 55], [0.05, 0.05, 0.05, 0.95]),
            ]
            predictions = [
                ([box], [0.99], [scores]) for box, scores in sequence
            ]
            tracks, next_id, statuses = {}, 0, []
            with patch("src.realtime_worker._get_predictions", side_effect=predictions):
                for unused in sequence:
                    unused_code, status, tracks, next_id = _analyze_frame(
                        CV2(), store, object(), Frame(), settings, "test", {},
                        tracks, next_id)
                    statuses.append(status)
            events = store.list_events()
            self.assertIn("ALERT", statuses)
            self.assertEqual(len(events), 1)
            self.assertIn("contact_started_at", events[0]["details"])
            self.assertIn("alert_at", events[0]["details"])
            evidence = Path(events[0]["evidence_path"])
            self.assertTrue(evidence.is_file())
            self.assertEqual(evidence.read_bytes(), (base / "latest.jpg").read_bytes())


class DatasetTests(unittest.TestCase):
    def test_inspection_counts_actual_files_and_annotation_states(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "ImageSets" / "Main").mkdir(parents=True)
            (root / "Annotations").mkdir()
            (root / "JPEGImages").mkdir()
            (root / "ImageSets" / "Main" / "train.txt").write_text("sample\n", encoding="utf-8")
            (root / "JPEGImages" / "sample.jpg").write_bytes(png_bytes(10, 8))
            (root / "Annotations" / "sample.xml").write_text(
                """<annotation><size><width>10</width><height>8</height></size>
                <object><name>hand</name><bndbox><xmin>1</xmin><ymin>1</ymin><xmax>8</xmax><ymax>7</ymax>
                <x1>1</x1><y1>1</y1><x2>8</x2><y2>1</y2><x3>8</x3><y3>7</y3><x4>1</x4><y4>7</y4></bndbox>
                <contact_state>0,1,2,0</contact_state></object></annotation>""",
                encoding="utf-8",
            )
            report = validate_dataset(root)
            self.assertEqual(read_image_dimensions(root / "JPEGImages" / "sample.jpg"), (10, 8))
            self.assertEqual(report["image_count"], 1)
            self.assertEqual(report["hand_annotation_count"], 1)
            self.assertEqual(report["contact_label_counts"]["Self-Contact"]["positive"], 1)
            self.assertEqual(report["contact_label_counts"]["Other-Person-Contact"]["unsure"], 1)
            self.assertEqual(report["error_count"], 0)

    def test_missing_dataset_is_reported(self):
        with tempfile.TemporaryDirectory() as directory:
            result = validate_dataset(Path(directory) / "missing")
            self.assertEqual(result["issues"][0]["code"], "DATASET_MISSING")
            self.assertEqual(result["error_count"], 1)


class SensorTests(unittest.TestCase):
    def test_unconfigured_and_mock_inputs_never_claim_hardware(self):
        self.assertFalse(UnconfiguredSensor().read()["available"])
        snapshot = MockSensor("MOTION").read()
        self.assertFalse(snapshot["available"])
        self.assertEqual(snapshot["source"], "mock")


class TrackingTests(unittest.TestCase):
    ROI = (40, 40, 60, 60)
    POLICY = {
        "track_timeout_seconds": 1.0, "track_match_distance_normalized": 0.25,
        "track_iou_threshold": 0.1, "movement_threshold_normalized": 0.015,
        "stationary_seconds": 2.0, "history_window_frames": 5,
        "minimum_contact_roi_frames": 3, "fast_contact_score": 0.85,
        "fast_contact_consecutive_frames": 2, "clear_after_seconds": 0.75,
        "cooldown_seconds": 2.0,
    }

    def hand(self, index, box, obj=0.0, person=0.0):
        result = analyze_predictions(
            [box], [0.99], [[0.05, 0.05, person, obj]],
            self.ROI, THRESHOLDS, 0.3)["hands"][0]
        result = dict(result)
        result["index"] = index
        return result

    def step(self, hands, tracks, next_id, now):
        tracks, next_id, observations = update_tracks(
            hands, tracks, next_id, now, 0.08, 1.0, 100, 100,
            self.ROI, 0.3, self.POLICY)
        by_index = {hand["index"]: hand for hand in hands}
        decisions = {}
        for track_id, track in tracks.items():
            hand = by_index.get(track.get("hand_index")) if track["frame_observed"] else None
            decisions[track_id] = advance_track_contact(
                track, hand, now, self.POLICY, 0.6, 0.3, True)
        return tracks, next_id, observations, decisions

    def test_outside_roi(self):
        tracks, next_id, unused, decisions = self.step(
            [self.hand(0, [0, 0, 10, 10], 0.99)], {}, 0, 0.0)
        self.assertEqual(decisions[0]["state"], "OUTSIDE_ROI")
        self.assertFalse(tracks[0]["alert_active"])

    def test_one_frame_in_roi_does_not_alert(self):
        tracks, next_id, unused, decisions = self.step(
            [self.hand(0, [20, 45, 30, 55], 0.99)], {}, 0, 0.0)
        tracks, next_id, unused, decisions = self.step(
            [self.hand(0, [42, 45, 52, 55], 0.99)], tracks, next_id, 0.1)
        self.assertEqual(decisions[0]["state"], "CANDIDATE")
        tracks, next_id, unused, decisions = self.step(
            [self.hand(0, [20, 45, 30, 55], 0.99)], tracks, next_id, 0.2)
        self.assertFalse(tracks[0]["alert_active"])

    def test_entry_and_consistent_contact_confirms_three_of_five(self):
        tracks, next_id, unused, decisions = self.step(
            [self.hand(0, [20, 45, 30, 55], 0.7)], {}, 0, 0.0)
        for frame in range(1, 4):
            tracks, next_id, unused, decisions = self.step(
                [self.hand(0, [42, 45, 52, 55], 0.7)], tracks, next_id, frame * 0.1)
        self.assertTrue(tracks[0]["alert_active"])
        self.assertEqual(decisions[0]["reason"], "object_contact_3_of_5_frames")

    def test_high_contact_fast_path_needs_two_frames(self):
        tracks, next_id, unused, decisions = self.step(
            [self.hand(0, [20, 45, 30, 55], 0.95)], {}, 0, 0.0)
        tracks, next_id, unused, decisions = self.step(
            [self.hand(0, [42, 45, 52, 55], 0.95)], tracks, next_id, 0.1)
        self.assertFalse(tracks[0]["alert_active"])
        tracks, next_id, unused, decisions = self.step(
            [self.hand(0, [42, 45, 52, 55], 0.95)], tracks, next_id, 0.2)
        self.assertTrue(tracks[0]["alert_active"])

    def test_real_touch_stays_alerted_and_only_starts_once(self):
        tracks, next_id, unused, decisions = self.step(
            [self.hand(0, [20, 45, 30, 55], 0.95)], {}, 0, 0.0)
        starts = 0
        for frame in range(1, 10):
            tracks, next_id, unused, decisions = self.step(
                [self.hand(0, [42, 45, 52, 55], 0.95)], tracks, next_id, frame * 0.1)
            starts += int(decisions[0]["alert_started"])
        self.assertEqual(starts, 1)
        self.assertEqual(decisions[0]["state"], "ALERT")

    def test_static_depicted_hand_at_start_stays_candidate(self):
        tracks, next_id = {}, 0
        for frame in range(10):
            tracks, next_id, unused, decisions = self.step(
                [self.hand(0, [45, 45, 55, 55], 0.99)], tracks, next_id, frame * 0.1)
        self.assertFalse(tracks[0]["ever_entered_roi"])
        self.assertEqual(decisions[0]["state"], "CANDIDATE")
        self.assertFalse(tracks[0]["alert_active"])

    def test_other_person_score_without_object_contact_does_not_alert(self):
        tracks, next_id = {}, 0
        for frame in range(5):
            tracks, next_id, unused, decisions = self.step(
                [self.hand(0, [45, 45, 55, 55], 0.1, person=0.95)],
                tracks, next_id, frame * 0.1)
        self.assertEqual(decisions[0]["state"], "NO_CONTACT")
        self.assertFalse(tracks[0]["alert_active"])

    def test_person_near_painting_without_object_contact_does_not_alert(self):
        tracks, next_id = {}, 0
        for frame in range(8):
            tracks, next_id, unused, decisions = self.step(
                [self.hand(0, [25, 45, 35, 55], 0.1)], tracks, next_id, frame * 0.1)
        self.assertEqual(decisions[0]["state"], "OUTSIDE_ROI")
        self.assertFalse(tracks[0]["alert_active"])

    def test_polygon_entry_sets_roi_entry_only_after_crossing(self):
        polygon = [(30, 20), (70, 20), (80, 80), (20, 80)]

        def make_hand(box):
            hand = analyze_predictions([box], [0.99], [[0.05, 0.05, 0.05, 0.95]],
                                       [20, 20, 80, 80], THRESHOLDS, 0.3,
                                       roi_polygon=polygon)["hands"][0]
            hand["index"] = 0
            return hand

        tracks, next_id, unused = update_tracks(
            [make_hand([75, 45, 85, 55])], {}, 0, 0.0, 0.08, 1.0,
            100, 100, (20, 20, 80, 80), 0.3, self.POLICY,
            roi_polygon=polygon)
        self.assertFalse(tracks[0]["ever_entered_roi"])
        tracks, next_id, observations = update_tracks(
            [make_hand([55, 45, 65, 55])], tracks, next_id, 0.1, 0.08, 1.0,
            100, 100, (20, 20, 80, 80), 0.3, self.POLICY,
            roi_polygon=polygon)
        self.assertTrue(tracks[0]["ever_entered_roi"])
        self.assertTrue(observations[0]["entered_roi"])

    def test_short_detection_miss_keeps_track_id(self):
        tracks, next_id, unused, unused_decisions = self.step(
            [self.hand(0, [5, 10, 15, 20])], {}, 0, 0.0)
        tracks, next_id, unused, unused_decisions = self.step([], tracks, next_id, 0.2)
        self.assertIn(0, tracks)
        tracks, next_id, observations, unused_decisions = self.step(
            [self.hand(0, [6, 10, 16, 20])], tracks, next_id, 0.3)
        self.assertEqual(observations[0]["track_id"], 0)

    def test_multiple_hands_are_matched_independent_of_order(self):
        tracks, next_id, obs, unused = self.step(
            [self.hand(0, [5, 10, 15, 20]), self.hand(1, [80, 10, 90, 20])],
            {}, 0, 0.0)
        old = {tuple(item["box"]): item["track_id"] for item in obs}
        tracks, next_id, obs, unused = self.step(
            [self.hand(0, [81, 10, 91, 20]), self.hand(1, [6, 10, 16, 20])],
            tracks, next_id, 0.1)
        new = {tuple(item["box"]): item["track_id"] for item in obs}
        self.assertEqual(new[(81.0, 10.0, 91.0, 20.0)], old[(80.0, 10.0, 90.0, 20.0)])
        self.assertEqual(new[(6.0, 10.0, 16.0, 20.0)], old[(5.0, 10.0, 15.0, 20.0)])

    def test_track_matching_uses_normalized_positions_across_resolutions(self):
        original = {"index": 0, "box": [10, 20, 20, 40], "roi_overlap": 0.0}
        tracks, next_id, unused = update_tracks(
            [original], {}, 0, 0.0, 0.08, 1.0, 100, 100,
            self.ROI, 0.3, self.POLICY)
        scaled = {"index": 0, "box": [110, 220, 210, 420], "roi_overlap": 0.0}
        tracks, next_id, observations = update_tracks(
            [scaled], tracks, next_id, 0.1, 0.08, 1.0, 1000, 1000,
            self.ROI, 0.3, self.POLICY)
        self.assertEqual(observations[0]["track_id"], 0)
        self.assertAlmostEqual(observations[0]["movement_normalized"],
                               (0.01 ** 2 + 0.02 ** 2) ** 0.5, places=6)


    def test_camera_interruption_expires_tracks_before_reconnect(self):
        tracks, next_id, unused, unused_decisions = self.step(
            [self.hand(0, [20, 45, 30, 55], 0.99)], {}, 0, 0.0)
        tracks, next_id, unused, unused_decisions = self.step([], tracks, next_id, 2.0)
        self.assertEqual(tracks, {})
        tracks, next_id, unused, decisions = self.step(
            [self.hand(0, [45, 45, 55, 55], 0.99)], tracks, next_id, 2.1)
        self.assertEqual(decisions[next(iter(tracks))]["state"], "CANDIDATE")
        self.assertFalse(next(iter(tracks.values()))["alert_active"])

    def test_stationary_contact_one_alert_and_exit_cooldown(self):
        tracks, next_id, unused, unused_decisions = self.step(
            [self.hand(0, [20, 45, 30, 55], 0.95)], {}, 0, 0.0)
        starts = 0
        for frame in range(1, 30):
            tracks, next_id, unused, decisions = self.step(
                [self.hand(0, [42, 45, 52, 55], 0.95)], tracks, next_id, frame * 0.1)
            starts += int(decisions[0]["alert_started"])
        self.assertEqual(starts, 1)
        self.assertTrue(tracks[0]["alert_active"])
        tracks, next_id, unused, decisions = self.step(
            [self.hand(0, [20, 45, 30, 55], 0.95)], tracks, next_id, 3.0)
        self.assertEqual(decisions[0]["state"], "COOLDOWN")
        self.assertFalse(tracks[0]["alert_active"])




if __name__ == "__main__":
    unittest.main()

