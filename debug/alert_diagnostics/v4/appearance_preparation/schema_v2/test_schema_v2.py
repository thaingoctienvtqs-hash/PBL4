"""SYNTHETIC_TEST only: schema/semantic tests, never AI/tracking accuracy."""
import copy
import csv
import io
import json
import unittest
from pathlib import Path
from unittest.mock import patch

import synthetic_cases as fixtures
from validate_v2 import (load_json, structural_errors, validate_bundle,
                         validation_report, asset_errors, SCHEMA_PATH)


class ValidCases(unittest.TestCase):
    def test_no_hand_without_reid_is_valid(self):
        b = fixtures.base()
        self.assertEqual([], b["hands"])
        self.assertNotIn("reidentification", b)
        self.assertEqual([], validate_bundle(b))

    def test_all_fixture_expectations(self):
        for name, (bundle, expected) in fixtures.cases().items():
            with self.subTest(name=name):
                self.assertEqual("SYNTHETIC_TEST", bundle["data_kind"])
                self.assertEqual(expected, not validate_bundle(bundle))

    def test_unknown_never_becomes_no_touch(self):
        b = fixtures.contact("UNKNOWN")
        before = copy.deepcopy(b)
        self.assertEqual([], validate_bundle(b))
        self.assertEqual(before, b)
        self.assertEqual("UNKNOWN", b["contact_events"][0]["label"])

    def test_approved_identity_does_not_imply_touch_or_roi_entry(self):
        b = fixtures.cases()["05_initial_inside.SYNTHETIC_TEST.json"][0]
        self.assertEqual([], validate_bundle(b))
        self.assertEqual("UNKNOWN", b["contact_events"][0]["label"])
        self.assertNotIn("ever_entered_roi", b["hands"][0])

    def test_hand_identity_and_temporal_gaps_are_annotations_not_recovery(self):
        b = fixtures.reid()
        self.assertEqual([], validate_bundle(b))
        self.assertEqual([], b["contact_events"])

    def test_full_coverage_is_not_an_automatic_default(self):
        b = fixtures.base()
        self.assertEqual("UNKNOWN", b["calibrations"][0]["coverage"]["status"])
        self.assertIsNone(b["sessions"][0]["camera"]["tilt_degrees"])
        self.assertIsNone(b["sessions"][0]["camera"]["fov_horizontal_degrees"])

    def test_explicit_measured_zero_tilt_is_not_null(self):
        b = fixtures.base()
        b["sessions"][0]["camera"].update(tilt_degrees=0, tilt_uncertainty_degrees=0)
        self.assertEqual([], validate_bundle(b))  # SYNTHETIC_TEST values only

    def test_bbox_on_all_four_edges_valid(self):
        b = fixtures.contact()
        b["hands"][0]["bbox_xyxy"] = [0, 0, 640, 480]
        self.assertEqual([], validate_bundle(b))

    def test_full_occlusion_without_fabricated_bbox(self):
        b = fixtures.contact("UNKNOWN")
        b["hands"][0].update(occlusion="FULL", bbox_xyxy=None, visibility_fraction=0)
        self.assertEqual([], validate_bundle(b))

    def test_empty_optional_reid_valid(self):
        b = fixtures.base()
        b["reidentification"] = {"identity_links": [], "pairs": []}
        self.assertEqual([], validate_bundle(b))

    def test_duplicate_tagged_frame_is_annotation_not_confirmation(self):
        b = fixtures.base()
        duplicate = fixtures.frame(1, 0)
        duplicate["timestamp_status"] = "DUPLICATE"
        b["frames"].append(duplicate)
        self.assertEqual([], validate_bundle(b))

    def test_host_and_capture_clocks_are_not_compared_as_same_epoch(self):
        b = fixtures.base()
        b["frames"][0].update(capture_timestamp_ms=9000, host_receive_timestamp_ms=1)
        self.assertEqual([], validate_bundle(b))

    def test_side_ground_truth_has_measured_sync(self):
        self.assertEqual([], validate_bundle(fixtures.side_touch()))

    def test_structurally_valid_does_not_certify_ai_metrics(self):
        r = validation_report(fixtures.base())
        self.assertEqual("PASS", r["authored_schema_subset_and_semantics"])
        self.assertIn(r["formal_draft7"], ("NOT_AVAILABLE", "PASS"))
        self.assertEqual("NOT_EVALUATED", r["ai_metrics"])

    def test_every_synthetic_fixture_blocked_from_real_evaluation(self):
        for name, (b, expected) in fixtures.cases().items():
            if expected:
                with self.subTest(name=name):
                    self.assertIn("SYNTHETIC_TEST is ineligible for real AI evaluation", validate_bundle(b, True))

    def test_missing_test_media_is_not_fabricated(self):
        errors = asset_errors(fixtures.base(), Path(__file__).parent)
        self.assertTrue(errors)
        self.assertTrue(all("asset missing:" in e for e in errors))

    def test_duplicate_json_keys_rejected_without_writing(self):
        with patch.object(Path, "open", return_value=io.StringIO('{"x":1,"x":2}')):
            with self.assertRaises(ValueError):
                load_json("not_written.json")

    def test_nonfinite_json_literal_rejected_without_writing(self):
        with patch.object(Path, "open", return_value=io.StringIO('{"x":NaN}')):
            with self.assertRaises(ValueError):
                load_json("not_written.json")

    def test_schema_local_references_and_supported_keywords(self):
        schema = load_json(SCHEMA_PATH)
        allowed = {"type", "additionalProperties", "properties", "required", "items", "minItems", "maxItems",
                   "uniqueItems", "minLength", "maxLength", "minimum", "maximum", "exclusiveMinimum",
                   "exclusiveMaximum", "enum", "const", "$ref", "$schema", "title", "description",
                   "definitions", "allOf", "anyOf", "if", "then", "else", "pattern"}
        def visit(rule):
            self.assertFalse(set(rule) - allowed)
            if "$ref" in rule:
                target = schema
                for part in rule["$ref"][2:].split("/"):
                    target = target[part]
            for key in ("properties", "definitions"):
                for child in rule.get(key, {}).values():
                    visit(child)
            for key in ("allOf", "anyOf"):
                for child in rule.get(key, []):
                    visit(child)
            for key in ("items", "if", "then", "else"):
                if key in rule:
                    visit(rule[key])
        visit(schema)

    def test_template_headers_and_no_fake_real_rows(self):
        schema = load_json(SCHEMA_PATH)
        mapping = {"sessions": "session", "videos": "video", "references": "reference_video",
                   "synchronizations": "synchronization", "calibrations": "calibration",
                   "frames": "frame", "hands": "hand", "tracking_gaps": "tracking_gap",
                   "contact_events": "contact_event", "reid_links": "identity_link", "reid_pairs": "pair"}
        for name, definition in mapping.items():
            with (Path(__file__).parent / (name + ".v2.template.csv")).open(encoding="utf-8", newline="") as inp:
                rows = list(csv.reader(inp))
            self.assertEqual([list(schema["definitions"][definition]["properties"])], rows)

    def test_saved_fixtures_equal_factories_and_expected_results(self):
        for name, (expected_bundle, valid) in fixtures.cases().items():
            b = load_json(Path(__file__).parent / "fixtures" / name)
            self.assertEqual(expected_bundle, b)
            self.assertEqual(valid, not validate_bundle(b))

    def test_validation_does_not_mutate_input(self):
        for b, valid in fixtures.cases().values():
            before = copy.deepcopy(b)
            validate_bundle(b)
            self.assertEqual(before, b)


class RejectionCases(unittest.TestCase):
    pass


DELETE = object()


def negative_case(factory, path, value):
    def test(self):
        b = factory()
        node = b
        for key in path[:-1]:
            node = node[key]
        if value is DELETE:
            del node[path[-1]]
        else:
            node[path[-1]] = copy.deepcopy(value)
        self.assertTrue(validate_bundle(b), "Invalid annotation unexpectedly accepted")
    return test


partial = fixtures.partial
contact = fixtures.contact
base = fixtures.base
reid = fixtures.reid
NEGATIVES = [
    ("missing_data_kind", base, ("data_kind",), DELETE),
    ("missing_video_id", base, ("videos", 0, "video_id"), DELETE),
    ("old_version", base, ("schema_version",), "1.0"),
    ("unexpected_field", base, ("threshold_override",), .01),
    ("ceiling_mount", base, ("sessions", 0, "camera", "mounting_position"), "CEILING"),
    ("front_view", base, ("sessions", 0, "camera", "viewing_direction"), "FRONTAL"),
    ("tilt_out_of_range", base, ("sessions", 0, "camera", "tilt_degrees"), 95),
    ("null_tilt_but_uncertainty_number", base, ("sessions", 0, "camera", "tilt_uncertainty_degrees"), 2),
    ("zero_fov", base, ("sessions", 0, "camera", "fov_horizontal_degrees"), 0),
    ("half_resolution", base, ("sessions", 0, "camera", "configured_resolution", "width"), 640),
    ("unknown_coverage_number", base, ("calibrations", 0, "coverage", "visible_surface_fraction"), .8),
    ("partial_without_blind_region", base, ("calibrations", 0, "coverage", "status"), "PARTIAL"),
    ("full_with_outside_fov", partial, ("calibrations", 0, "coverage"), {
        "status": "FULL", "visible_surface_fraction": 1, "observable_surface_fraction": 1,
        "unobservable_regions": [{"region_id": "r", "reason": "OUTSIDE_FOV", "coordinate_space": "UNKNOWN",
                                 "coordinates": None, "notes": "SYNTHETIC_TEST contradiction."}], "notes": ""}),
    ("observable_more_than_visible", partial, ("calibrations", 0, "coverage"), {
        "status": "PARTIAL", "visible_surface_fraction": .3, "observable_surface_fraction": .8,
        "unobservable_regions": [{"region_id": "r", "reason": "OUTSIDE_FOV", "coordinate_space": "UNKNOWN",
                                 "coordinates": None, "notes": "SYNTHETIC_TEST."}], "notes": ""}),
    ("outside_fov_in_image_coords", partial, ("calibrations", 0, "coverage", "unobservable_regions", 0, "coordinate_space"), "IMAGE_NORMALIZED"),
    ("unmeasured_calibration_has_reference", base, ("calibrations", 0, "reference_frame_id"), "f0"),
    ("roi_out_of_bounds", partial, ("calibrations", 0, "roi", "coordinates", 0), [-.01, .1]),
    ("roi_self_crossing", partial, ("calibrations", 0, "roi", "coordinates"), [[.1,.1],[.9,.9],[.1,.9],[.9,.1]]),
    ("roi_repeated_vertex", partial, ("calibrations", 0, "roi", "coordinates"), [[.1,.1],[.9,.1],[.9,.1],[.1,.9]]),
    ("roi_concave_unsupported", partial, ("calibrations", 0, "roi", "coordinates"), [[.1,.1],[.9,.1],[.4,.4],[.1,.9]]),
    ("slanted_rectangle", partial, ("calibrations", 0, "roi", "shape"), "rectangle"),
    ("roi_not_normalized_bool", partial, ("calibrations", 0, "roi", "normalized"), "true"),
    ("roi_space_mismatch", partial, ("calibrations", 0, "roi", "image_space"), "UNDISTORTED"),
    ("singular_homography", partial, ("calibrations", 0, "homography_image_to_artwork"), [[0,0,0],[0,0,0],[0,0,0]]),
    ("frame_space_mismatch", base, ("frames", 0, "image_space"), "UNDISTORTED"),
    ("frame_clock_mismatch", base, ("frames", 0, "capture_clock_id"), "host_clock"),
    ("frame_resolution_mismatch", base, ("frames", 0, "width"), 320),
    ("frame_source_mismatch", base, ("frames", 0, "source_id"), "other_source"),
    ("frame_calibration_missing", base, ("frames", 0, "calibration_id"), "missing"),
    ("negative_timestamp", base, ("frames", 0, "capture_timestamp_ms"), -1),
    ("boolean_timestamp", base, ("frames", 0, "capture_timestamp_ms"), True),
    ("nan_timestamp", base, ("frames", 0, "capture_timestamp_ms"), float("nan")),
    ("huge_timestamp", base, ("frames", 0, "capture_timestamp_ms"), 10 ** 1000),
    ("unknown_timestamp_filled", base, ("frames", 0, "timestamp_status"), "UNKNOWN"),
    ("valid_timestamp_null", base, ("frames", 0, "capture_timestamp_ms"), None),
    ("duplicate_without_prior", base, ("frames", 0, "timestamp_status"), "DUPLICATE"),
    ("offline_with_live_image", base, ("frames", 0, "camera_state"), "OFFLINE"),
    ("hand_missing_frame", contact, ("hands", 0, "frame_id"), "missing"),
    ("bbox_negative", contact, ("hands", 0, "bbox_xyxy"), [-1, 0, 200, 200]),
    ("bbox_outside", contact, ("hands", 0, "bbox_xyxy"), [0, 0, 641, 480]),
    ("bbox_reversed", contact, ("hands", 0, "bbox_xyxy"), [100, 0, 0, 100]),
    ("bbox_zero_area", contact, ("hands", 0, "bbox_xyxy"), [100, 0, 100, 100]),
    ("bbox_bool", contact, ("hands", 0, "bbox_xyxy"), [False, 0, 100, 100]),
    ("full_occlusion_bbox_fabricated", contact, ("hands", 0, "occlusion"), "FULL"),
    ("unoccluded_visibility_partial", contact, ("hands", 0, "visibility_fraction"), .5),
    ("identity_verified_without_hand", contact, ("hands", 0, "hand_id"), None),
    ("printed_with_physical_identity", contact, ("hands", 0, "entity_kind"), "DEPICTED_HAND"),
    ("inside_location_without_roi", contact, ("hands", 0, "first_observed_location"), "INSIDE_ROI"),
    ("known_touch_unverifiable", contact, ("contact_events", 0, "ground_truth", "verification_status"), "UNVERIFIABLE"),
    ("known_touch_unresolved_source", contact, ("contact_events", 0, "ground_truth", "sources", 0, "kind"), "UNRESOLVED"),
    ("touch_not_reviewed", contact, ("contact_events", 0, "ground_truth", "review", "status"), "DRAFT"),
    ("one_reviewer_approved", contact, ("contact_events", 0, "ground_truth", "review", "reviewer_ids"), ["one"]),
    ("near_without_definition", lambda: contact("NEAR_NO_TOUCH"), ("contact_events", 0, "near_definition"), None),
    ("unknown_forced_verified", lambda: contact("UNKNOWN"), ("contact_events", 0, "ground_truth", "verification_status"), "VERIFIED"),
    ("event_end_before_start", contact, ("contact_events", 0, "end_timestamp_ms"), 0),
    ("event_exceeds_video", contact, ("contact_events", 0, "end_timestamp_ms"), 11000),
    ("event_missing_observation", contact, ("contact_events", 0, "observation_ids"), ["missing"]),
    ("event_without_hand_evidence", contact, ("contact_events", 0, "observation_ids"), []),
    ("event_wrong_hand", contact, ("contact_events", 0, "hand_id"), "h2"),
    ("side_wrong_sync", fixtures.side_touch, ("contact_events", 0, "ground_truth", "sources", 0, "sync_id"), "missing"),
    ("same_pair_other_hand", reid, ("reidentification", "pairs", 0, "query_observation_id"), "o4"),
    ("future_gallery", reid, ("reidentification", "pairs", 0, "gallery_observation_id"), "o3"),
    ("identity_link_endpoint_changed", reid, ("reidentification", "identity_links", 0, "after_observation_id"), "o4"),
    ("gap_endpoint_missing", reid, ("tracking_gaps", 0, "after_observation_id"), "missing"),
    ("gap_reverse_interval", reid, ("tracking_gaps", 0, "end_timestamp_ms"), 0),
    ("path_traversal", base, ("videos", 0, "relative_path"), "../other.mp4"),
]
for name, factory, path, value in NEGATIVES:
    setattr(RejectionCases, "test_reject_" + name, negative_case(factory, path, value))


class Contradictions(unittest.TestCase):
    def test_monotonic_valid_time_required(self):
        b = base()
        b["frames"].append(fixtures.frame(1, 0))
        self.assertTrue(validate_bundle(b))

    def test_hand_in_offline_frame_rejected(self):
        b = contact()
        b["frames"][0].update(frame_status="OFFLINE", camera_state="OFFLINE", capture_timestamp_ms=None,
                               timestamp_status="UNKNOWN", raw_image_path=None, raw_image_sha256=None,
                               width=None, height=None)
        self.assertTrue(validate_bundle(b))

    def test_printed_hand_cannot_verify_touch(self):
        b = fixtures.cases()["04_depicted_hand.SYNTHETIC_TEST.json"][0]
        e = fixtures.event("TOUCH")
        e.update(observation_ids=["o1"], scope="HAND")
        b["contact_events"] = [e]
        self.assertTrue(validate_bundle(b))

    def test_unsynchronized_side_camera_cannot_verify_primary_contact(self):
        b = fixtures.side_touch()
        b["synchronizations"][0].update(status="UNKNOWN", method="UNKNOWN", primary_anchor_ms=None,
                                        offset_ms=None, uncertainty_ms=None, drift_ppm=None)
        self.assertTrue(validate_bundle(b))

    def test_conflicting_scene_and_hand_contact(self):
        b = contact()
        e = fixtures.event("NO_TOUCH")
        e["event_id"] = "e2"
        b["contact_events"].append(e)
        self.assertTrue(validate_bundle(b))

    def test_two_hands_may_have_different_simultaneous_contact_labels(self):
        b = fixtures.crossing()
        e1, e2 = fixtures.event("TOUCH"), fixtures.event("NEAR_NO_TOUCH")
        e1.update(hand_id="h1", observation_ids=["o1"], scope="HAND")
        e2.update(event_id="e2", hand_id="h2", observation_ids=["o2"], scope="HAND")
        b["contact_events"] = [e1, e2]
        self.assertEqual([], validate_bundle(b))

    def test_hand_identity_side_cannot_swap_at_crossing(self):
        b = fixtures.crossing()
        b["hands"][2]["side"] = "RIGHT"
        self.assertTrue(validate_bundle(b))

    def test_same_capture_group_cannot_leak_between_splits(self):
        b = base()
        s = copy.deepcopy(b["sessions"][0])
        s.update(session_id="s2", split="test")
        b["sessions"].append(s)
        self.assertTrue(validate_bundle(b))

    def test_invalid_cross_references_report_errors_instead_of_crashing(self):
        b = reid()
        b["hands"][0]["frame_id"] = "missing"
        self.assertTrue(validate_bundle(b))

    def test_input_with_nonobject_root_is_rejected(self):
        self.assertTrue(validate_bundle([]))




class AdditionalQuality(unittest.TestCase):
    def test_frame_pts_outside_video_rejected(self):
        b = fixtures.base()
        b["frames"][0]["capture_timestamp_ms"] = 11000
        self.assertTrue(validate_bundle(b))

    def test_scene_scope_cannot_claim_specific_hand(self):
        b = fixtures.contact()
        b["contact_events"][0]["scope"] = "SCENE"
        self.assertTrue(validate_bundle(b))

    def test_exact_media_hash_leakage_even_with_different_group_ids(self):
        b = fixtures.base()
        b["sessions"][0]["split"] = "validation"
        s = copy.deepcopy(b["sessions"][0])
        s.update(session_id="s2", capture_group_id="group2", split="test")
        b["sessions"].append(s)
        v = copy.deepcopy(b["videos"][0])
        v.update(video_id="v2", session_id="s2", segment_id="segment2")
        b["videos"].append(v)
        self.assertTrue(validate_bundle(b))

    def test_schema_pass_does_not_certify_evaluation_readiness(self):
        self.assertEqual("NOT_CERTIFIED", validation_report(fixtures.base())["evaluation_readiness"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
