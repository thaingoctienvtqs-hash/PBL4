"""SYNTHETIC_TEST fixture factories. No images, video, AI inference or real labels.
Every returned bundle is synthetic and must be refused by --require-real.
Numeric geometry/timing is arbitrary test input, not measured ArtGuard setup.
"""
import copy


def review():
    return {"status": "APPROVED", "reviewer_ids": ["SYNTHETIC_TEST_REVIEWER_A", "SYNTHETIC_TEST_REVIEWER_B"],
            "notes": "SYNTHETIC_TEST only; no human/video verification was performed."}


def frame(index=0, timestamp=0):
    return {"session_id": "s1", "video_id": "v1", "source_id": "cam1", "frame_id": "f" + str(index),
            "source_frame_id": None, "sequence_index": index, "capture_clock_id": "capture_clock",
            "capture_timestamp_ms": timestamp, "host_clock_id": "host_clock",
            "host_receive_timestamp_ms": 100000 + index * 100, "timestamp_status": "VALID",
            "frame_status": "OK", "camera_state": "UNKNOWN",
            "raw_image_path": "SYNTHETIC_TEST/frame_" + str(index) + ".jpg",
            "raw_image_sha256": str(index % 10) * 64, "width": 640, "height": 480,
            "calibration_id": "c1", "image_space": "RAW", "observation_notes": "SYNTHETIC_TEST; media does not exist."}


def base():
    return {
        "schema_version": "2.0", "data_kind": "SYNTHETIC_TEST", "dataset_id": "SYNTHETIC_TEST_ONLY",
        "annotation_version": "SYNTHETIC_TEST_1", "coordinate_convention": "ZERO_BASED_CONTINUOUS_PIXEL_XYXY",
        "sessions": [{"session_id": "s1", "capture_group_id": "group1", "source_id": "cam1",
                      "camera": {"camera_id": "cam1", "sensor": "OV3660", "mounting_position": "TOP_EDGE_DIRECT",
                                 "viewing_direction": "OBLIQUE_DOWNWARD", "tilt_degrees": None,
                                 "tilt_convention": "DEGREES_FROM_ARTWORK_PLANE_0_PARALLEL_90_NORMAL",
                                 "tilt_uncertainty_degrees": None, "fov_horizontal_degrees": None,
                                 "fov_vertical_degrees": None, "configured_resolution": {"width": None, "height": None},
                                 "measurement_notes": "SYNTHETIC_TEST. Actual camera angle/FOV/resolution unmeasured."},
                      "artwork_id": "SYNTHETIC_TEST_ARTWORK", "host_clock_id": "host_clock", "person_group_ids": ["p1", "p2"],
                      "split": "unassigned", "scenario_tags": ["SYNTHETIC_TEST"], "review": review()}],
        "videos": [{"video_id": "v1", "session_id": "s1", "segment_id": "segment1", "media_kind": "RAW_VIDEO",
                    "relative_path": "SYNTHETIC_TEST/not_a_real_video.mp4", "sha256": "0" * 64,
                    "capture_clock_id": "capture_clock", "timestamp_basis": "VIDEO_PTS",
                    "duration_ms": 10000, "nominal_fps": None, "resolution": {"width": 640, "height": 480}}],
        "reference_videos": [], "synchronizations": [],
        "calibrations": [{"calibration_id": "c1", "video_id": "v1", "status": "UNMEASURED",
                          "reference_frame_id": None, "image_space": "RAW", "roi": None,
                          "coverage": {"status": "UNKNOWN", "visible_surface_fraction": None,
                                       "observable_surface_fraction": None, "unobservable_regions": [],
                                       "notes": "SYNTHETIC_TEST; no coverage measurements."},
                          "artwork_width_mm": None, "artwork_height_mm": None, "intrinsics_id": None,
                          "homography_image_to_artwork": None, "homography_reprojection_error_px": None,
                          "notes": "SYNTHETIC_TEST; no calibration was run."}],
        "frames": [frame()], "hands": [], "tracking_gaps": [], "contact_events": []}


def hand(oid="o1", fid="f0", hid="h1", person="p1", side="LEFT", box=None):
    return {"observation_id": oid, "session_id": "s1", "video_id": "v1", "frame_id": fid,
            "entity_kind": "REAL_HAND", "hand_id": hid, "person_group_id": person,
            "depiction_id": None, "identity_status": "VERIFIED", "side": side,
            "bbox_xyxy": [200, 180, 280, 260] if box is None else box,
            "occlusion": "NONE", "visibility_fraction": 1,
            "first_observed_location": "UNKNOWN", "review": review()}


def event(label="NO_TOUCH"):
    unknown = label == "UNKNOWN"
    return {"event_id": "e1", "session_id": "s1", "video_id": "v1", "hand_id": None,
            "observation_ids": [], "scope": "SCENE", "label": label,
            "start_frame_id": "f0", "end_frame_id": "f0", "start_timestamp_ms": 0,
            "end_timestamp_ms": 1000, "boundary_uncertainty_ms": None,
            "near_definition": "SYNTHETIC_TEST near policy; no real distance measured." if label == "NEAR_NO_TOUCH" else None,
            "ground_truth": {"verification_status": "UNVERIFIABLE" if unknown else "VERIFIED",
                             "sources": [{"kind": "UNRESOLVED" if unknown else "INDEPENDENT_OBSERVER",
                                          "video_id": None, "reference_id": None, "sync_id": None,
                                          "evidence_notes": "SYNTHETIC_TEST fixture, not actual evidence."}],
                             "review": review()}}


def contact(label="TOUCH"):
    b = base()
    b["hands"] = [hand()]
    e = event(label)
    e.update(hand_id="h1", observation_ids=["o1"], scope="HAND")
    b["contact_events"] = [e]
    return b


def partial():
    b = base()
    c = b["calibrations"][0]
    c.update(status="ANNOTATED", reference_frame_id="f0",
             roi={"shape": "polygon", "normalized": True, "image_space": "RAW",
                  "coordinates": [[.1, .1], [.9, .2], [.8, .9], [.2, .8]]})
    c["coverage"].update(status="PARTIAL", unobservable_regions=[
        {"region_id": "blind1", "reason": "OUTSIDE_FOV", "coordinate_space": "UNKNOWN",
         "coordinates": None, "notes": "SYNTHETIC_TEST; extent unknown, not inferred beyond FOV."}])
    return b


def crossing():
    b = base()
    b["frames"].append(frame(1, 200))
    b["hands"] = [hand("o1", "f0", box=[100, 180, 180, 260]),
                  hand("o2", "f0", "h2", "p2", "RIGHT", [300, 180, 380, 260]),
                  hand("o3", "f1", box=[300, 180, 380, 260]),
                  hand("o4", "f1", "h2", "p2", "RIGHT", [100, 180, 180, 260])]
    return b


def reid():
    b = crossing()
    b["tracking_gaps"] = [{"gap_id": "g1", "session_id": "s1", "video_id": "v1",
                           "before_observation_id": "o1", "after_observation_id": "o3",
                           "start_timestamp_ms": 1, "end_timestamp_ms": 199, "gap_kind": "DETECTION_GAP",
                           "continuity": "SAME_HAND", "review": review()}]
    b["reidentification"] = {
        "identity_links": [{"link_id": "l1", "gap_id": "g1", "before_observation_id": "o1",
                            "after_observation_id": "o3", "label": "SAME_HAND", "review": review()}],
        "pairs": [{"pair_id": "pair1", "gap_id": "g1", "gallery_observation_id": "o1",
                   "query_observation_id": "o3", "label": "SAME_HAND",
                   "difficulty_tags": ["SYNTHETIC_TEST", "CROSSING"], "review": review()}]}
    return b


def side_touch():
    b = contact()
    b["reference_videos"] = [{"reference_id": "r1", "session_id": "s1",
                              "view": "SIDE_GROUND_TRUTH_ONLY", "relative_path": "SYNTHETIC_TEST/side.mp4",
                              "sha256": "1" * 64, "clock_id": "side_clock"}]
    b["synchronizations"] = [{"sync_id": "sync1", "video_id": "v1", "reference_id": "r1",
                              "status": "MEASURED", "method": "VISUAL_MARKER",
                              "mapping": "REFERENCE_MS_EQUALS_PRIMARY_MS_PLUS_OFFSET_AT_ANCHOR",
                              "primary_anchor_ms": 0, "offset_ms": 100, "uncertainty_ms": 12,
                              "drift_ppm": None, "notes": "SYNTHETIC_TEST values; no actual synchronization."}]
    b["contact_events"][0]["ground_truth"]["sources"] = [
        {"kind": "SIDE_REFERENCE", "video_id": None, "reference_id": "r1", "sync_id": "sync1",
         "evidence_notes": "SYNTHETIC_TEST side-camera label."}]
    return b


def cases():
    nohand = base()
    nohand["contact_events"] = [event()]
    printed = base()
    o = hand()
    o.update(entity_kind="DEPICTED_HAND", hand_id=None, person_group_id=None, depiction_id="printed1",
             identity_status="NOT_APPLICABLE", side="NOT_APPLICABLE")
    printed["hands"] = [o]
    printed["contact_events"] = [event()]
    initial = partial()
    initial["hands"] = [hand()]
    initial["hands"][0]["first_observed_location"] = "INSIDE_ROI"
    initial["contact_events"] = [event("UNKNOWN")]
    moving = base()
    moving["frames"][0]["camera_state"] = "MOVING"
    moving["frames"].append(frame(1, 100))
    moving["frames"][1].update(frame_status="OFFLINE", camera_state="OFFLINE",
                               capture_timestamp_ms=None, timestamp_status="UNKNOWN",
                               raw_image_path=None, raw_image_sha256=None, width=None, height=None)
    unknown = base()
    unknown["frames"][0].update(capture_timestamp_ms=None, host_receive_timestamp_ms=None, timestamp_status="UNKNOWN")
    unknown["videos"][0].update(timestamp_basis="UNKNOWN", duration_ms=None)
    invalid = base()
    del invalid["videos"][0]["video_id"]
    return {
        "01_no_hand.SYNTHETIC_TEST.json": (nohand, True),
        "02_touch.SYNTHETIC_TEST.json": (contact(), True),
        "03_near_no_touch.SYNTHETIC_TEST.json": (contact("NEAR_NO_TOUCH"), True),
        "04_depicted_hand.SYNTHETIC_TEST.json": (printed, True),
        "05_initial_inside.SYNTHETIC_TEST.json": (initial, True),
        "06_two_hands_crossing.SYNTHETIC_TEST.json": (crossing(), True),
        "07_moving_offline.SYNTHETIC_TEST.json": (moving, True),
        "08_timestamp_unknown.SYNTHETIC_TEST.json": (unknown, True),
        "09_partial_roi.SYNTHETIC_TEST.json": (partial(), True),
        "10_invalid_missing_video_id.SYNTHETIC_TEST.json": (invalid, False),
        "11_optional_reid.SYNTHETIC_TEST.json": (reid(), True),
        "12_side_reference_touch.SYNTHETIC_TEST.json": (side_touch(), True)}
