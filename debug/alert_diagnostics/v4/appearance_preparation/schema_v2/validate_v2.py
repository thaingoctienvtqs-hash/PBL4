"""Read-only ArtGuard v2 annotation checks. Python 3.7, standard library.
The structural walker covers this authored schema's keywords; it is NOT a
general/conformance-certified Draft 7 implementation. Use jsonschema too when
already installed. No annotation migration, runtime ROI import or AI execution.
"""
import argparse
import hashlib
import importlib.util
import json
import math
from pathlib import Path

SCHEMA_PATH = Path(__file__).with_name("annotation_bundle.v2.schema.json")


def load_json(path):
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("Duplicate JSON key: " + key)
            result[key] = value
        return result

    def invalid(value):
        raise ValueError("Non-finite JSON literal: " + value)

    with Path(path).open(encoding="utf-8") as inp:
        return json.load(inp, object_pairs_hook=unique, parse_constant=invalid)


def finite_number(value):
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        return False
    try:
        return math.isfinite(value)
    except OverflowError:
        return False


def structural_errors(value, schema=None):
    """Subset checks only; semantic/cross-reference rules are checked separately."""
    root = load_json(SCHEMA_PATH) if schema is None else schema

    def walk(data, rule, path):
        errors = []
        if "$ref" in rule:
            target = root
            for part in rule["$ref"][2:].split("/"):
                target = target[part.replace("~1", "/").replace("~0", "~")]
            errors.extend(walk(data, target, path))
        types = {
            "object": lambda x: isinstance(x, dict),
            "array": lambda x: isinstance(x, list),
            "string": lambda x: isinstance(x, str),
            "number": finite_number,
            "integer": lambda x: finite_number(x) and int(x) == x,
            "boolean": lambda x: isinstance(x, bool),
            "null": lambda x: x is None,
        }
        if "type" in rule and not types[rule["type"]](data):
            return errors + [path + ": type must be " + rule["type"]]
        if "const" in rule and (data != rule["const"] or isinstance(data, bool) != isinstance(rule["const"], bool)):
            errors.append(path + ": const mismatch")
        if "enum" in rule and not any(data == x and isinstance(data, bool) == isinstance(x, bool) for x in rule["enum"]):
            errors.append(path + ": enum mismatch")
        if "anyOf" in rule and not any(not walk(data, branch, path) for branch in rule["anyOf"]):
            errors.append(path + ": no anyOf branch matches")
        for branch in rule.get("allOf", []):
            errors.extend(walk(data, branch, path))
        if "if" in rule:
            branch = "then" if not walk(data, rule["if"], path) else "else"
            if branch in rule:
                errors.extend(walk(data, rule[branch], path))
        if isinstance(data, dict):
            props = rule.get("properties", {})
            for key in rule.get("required", []):
                if key not in data:
                    errors.append(path + ": missing " + key)
            if rule.get("additionalProperties") is False:
                for key in set(data) - set(props):
                    errors.append(path + ": unexpected " + key)
            for key, child in props.items():
                if key in data:
                    errors.extend(walk(data[key], child, path + "." + key))
        if isinstance(data, list):
            if len(data) < rule.get("minItems", 0) or len(data) > rule.get("maxItems", float("inf")):
                errors.append(path + ": array length")
            if rule.get("uniqueItems") and len({json.dumps(x, sort_keys=True) for x in data}) != len(data):
                errors.append(path + ": duplicate array item")
            if "items" in rule:
                for i, child in enumerate(data):
                    errors.extend(walk(child, rule["items"], path + "[" + str(i) + "]"))
        if isinstance(data, str):
            import re
            if len(data) < rule.get("minLength", 0) or len(data) > rule.get("maxLength", float("inf")):
                errors.append(path + ": string length")
            if "pattern" in rule and re.search(rule["pattern"], data) is None:
                errors.append(path + ": pattern mismatch")
        if finite_number(data):
            if data < rule.get("minimum", -float("inf")) or data > rule.get("maximum", float("inf")):
                errors.append(path + ": numeric bounds")
            if "exclusiveMinimum" in rule and data <= rule["exclusiveMinimum"]:
                errors.append(path + ": exclusive minimum")
            if "exclusiveMaximum" in rule and data >= rule["exclusiveMaximum"]:
                errors.append(path + ": exclusive maximum")
        return errors

    return walk(value, root, "$")


def polygon_errors(points, convex=True):
    """No image processing: validate normalized annotation geometry only."""
    if len(set(tuple(p) for p in points)) != len(points):
        return ["duplicate polygon vertex"]
    area2 = sum(a[0] * b[1] - b[0] * a[1] for a, b in zip(points, points[1:] + points[:1]))
    if abs(area2) <= 1e-12:
        return ["zero polygon area"]

    def cross(a, b, c):
        return (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0])

    def on(a, b, p):
        return abs(cross(a, b, p)) <= 1e-12 and min(a[0], b[0]) <= p[0] <= max(a[0], b[0]) and min(a[1], b[1]) <= p[1] <= max(a[1], b[1])

    def intersects(a, b, c, d):
        x, y, z, w = cross(a, b, c), cross(a, b, d), cross(c, d, a), cross(c, d, b)
        return x * y < 0 and z * w < 0 or on(a, b, c) or on(a, b, d) or on(c, d, a) or on(c, d, b)

    n = len(points)
    for i in range(n):
        for j in range(i + 1, n):
            if j == i + 1 or i == 0 and j == n - 1:
                continue
            if intersects(points[i], points[(i + 1) % n], points[j], points[(j + 1) % n]):
                return ["self-intersecting polygon"]
    turns = [cross(points[i - 1], points[i], points[(i + 1) % n]) for i in range(n)]
    if convex and (any(abs(x) <= 1e-12 for x in turns) or not (all(x > 0 for x in turns) or all(x < 0 for x in turns))):
        return ["ROI must be strictly convex in perimeter order"]
    return []


def semantic_errors(bundle):
    errors = []

    def bad(message):
        errors.append(message)

    def index(rows, key):
        result = {}
        for row in rows:
            value = row[key]
            if value in result:
                bad("duplicate " + key + ": " + value)
            result[value] = row
        return result

    sessions = index(bundle["sessions"], "session_id")
    videos = index(bundle["videos"], "video_id")
    references = index(bundle["reference_videos"], "reference_id")
    syncs = index(bundle["synchronizations"], "sync_id")
    calibrations = index(bundle["calibrations"], "calibration_id")
    frames = index(bundle["frames"], "frame_id")
    hands = index(bundle["hands"], "observation_id")
    gaps = index(bundle["tracking_gaps"], "gap_id")
    index(bundle["contact_events"], "event_id")
    groups = {}
    for s in sessions.values():
        group = s["capture_group_id"]
        if group in groups and groups[group] != s["split"]:
            bad("capture_group split leakage: " + group)
        groups[group] = s["split"]
    for v in videos.values():
        if v["session_id"] not in sessions:
            bad("video session reference: " + v["video_id"])
    for r in references.values():
        if r["session_id"] not in sessions:
            bad("reference session reference: " + r["reference_id"])
    for x in syncs.values():
        v, r = videos.get(x["video_id"]), references.get(x["reference_id"])
        if not v or not r or v["session_id"] != r["session_id"]:
            bad("synchronization scope: " + x["sync_id"])
    for c in calibrations.values():
        v = videos.get(c["video_id"])
        if not v:
            bad("calibration video reference: " + c["calibration_id"])
        rf = frames.get(c["reference_frame_id"])
        if c["reference_frame_id"] is not None and (not rf or rf["video_id"] != c["video_id"] or rf["frame_status"] != "OK"):
            bad("calibration reference frame: " + c["calibration_id"])
        roi = c["roi"]
        if roi:
            if roi["image_space"] != c["image_space"]:
                bad("ROI coordinate-space mismatch")
            errors.extend("ROI: " + e for e in polygon_errors(roi["coordinates"]))
            if roi["shape"] == "rectangle":
                xs, ys = {p[0] for p in roi["coordinates"]}, {p[1] for p in roi["coordinates"]}
                if len(xs) != 2 or len(ys) != 2:
                    bad("rectangle must have axis-aligned corners; use polygon for perspective")
        cover = c["coverage"]
        visible, observable = cover["visible_surface_fraction"], cover["observable_surface_fraction"]
        if visible is not None and observable is not None and observable > visible:
            bad("observable coverage exceeds visible coverage")
        for region in cover["unobservable_regions"]:
            if region["reason"] == "OUTSIDE_FOV":
                if cover["status"] == "FULL":
                    bad("FULL coverage contradicts OUTSIDE_FOV")
                if region["coordinate_space"] == "IMAGE_NORMALIZED":
                    bad("OUTSIDE_FOV must use artwork coordinates or UNKNOWN")
            if region["coordinates"] is not None:
                if region["coordinate_space"] == "UNKNOWN":
                    bad("unknown region has fabricated geometry")
                errors.extend("region: " + e for e in polygon_errors(region["coordinates"], False))
        h = c["homography_image_to_artwork"]
        if h is None and c["homography_reprojection_error_px"] is not None:
            bad("homography error without homography")
        if h is not None:
            scale = max(abs(x) for row in h for x in row)
            a = [[x / scale for x in row] for row in h] if scale else [[0] * 3 for _ in range(3)]
            determinant = a[0][0] * (a[1][1] * a[2][2] - a[1][2] * a[2][1]) - a[0][1] * (a[1][0] * a[2][2] - a[1][2] * a[2][0]) + a[0][2] * (a[1][0] * a[2][1] - a[1][1] * a[2][0])
            if abs(determinant) <= 1e-12:
                bad("singular or numerically degenerate homography")
            if c["status"] == "VERIFIED" and c["homography_reprojection_error_px"] is None:
                bad("verified homography needs measured reprojection error")
    hash_splits = {}
    assets = [(v["sha256"], v["session_id"]) for v in videos.values()] + [(r["sha256"], r["session_id"]) for r in references.values()]
    assets += [(f["raw_image_sha256"], f["session_id"]) for f in bundle["frames"] if f["raw_image_sha256"] is not None]
    for digest, session_id in assets:
        session = sessions.get(session_id)
        if session and session["split"] != "unassigned":
            split = session["split"]
            if digest in hash_splits and hash_splits[digest] != split:
                bad("exact media/image hash leakage between splits")
            hash_splits[digest] = split
    sequence, last_valid, seen_times = {}, {}, {}
    for f in bundle["frames"]:
        v, s, c = videos.get(f["video_id"]), sessions.get(f["session_id"]), calibrations.get(f["calibration_id"])
        if not v or not s or v["session_id"] != f["session_id"] or f["source_id"] != s["source_id"]:
            bad("frame session/video/source scope: " + f["frame_id"])
        if v and f["capture_clock_id"] != v["capture_clock_id"] or s and f["host_clock_id"] != s["host_clock_id"]:
            bad("frame clock mismatch: " + f["frame_id"])
        if not c or c["video_id"] != f["video_id"]:
            bad("frame calibration scope: " + f["frame_id"])
        if c and f["image_space"] != c["image_space"]:
            bad("frame/calibration image-space mismatch")
        if v and f["frame_status"] == "OK" and v["resolution"]["width"] is not None and (f["width"], f["height"]) != (v["resolution"]["width"], v["resolution"]["height"]):
            bad("frame resolution differs from video; explicit derivative contract required")
        key = f["video_id"]
        if f["sequence_index"] <= sequence.get(key, -1):
            bad("sequence_index must increase within video")
        sequence[key] = f["sequence_index"]
        t = f["capture_timestamp_ms"]
        if v and v["timestamp_basis"] == "VIDEO_PTS" and v["duration_ms"] is not None and t is not None and t > v["duration_ms"]:
            bad("frame PTS exceeds video duration")
        if f["timestamp_status"] == "VALID":
            if t <= last_valid.get(key, -1):
                bad("VALID capture timestamps must increase")
            last_valid[key] = t
        if f["timestamp_status"] == "DUPLICATE" and t is not None and t not in seen_times.get(key, set()):
            bad("DUPLICATE timestamp has no prior observation")
        if t is not None:
            seen_times.setdefault(key, set()).add(t)
    hand_meta = {}
    for o in hands.values():
        f = frames.get(o["frame_id"])
        if not f or o["session_id"] not in sessions or f["session_id"] != o["session_id"] or f["video_id"] != o["video_id"] or f["frame_status"] != "OK":
            bad("hand observation needs matching OK frame: " + o["observation_id"])
            continue
        oc = calibrations.get(f["calibration_id"])
        if o["first_observed_location"] != "UNKNOWN" and (not oc or oc["roi"] is None):
            bad("known ROI location requires an annotated ROI")
        b = o["bbox_xyxy"]
        if b is not None and not (0 <= b[0] < b[2] <= f["width"] and 0 <= b[1] < b[3] <= f["height"]):
            bad("bbox positive area/bounds: " + o["observation_id"])
        if o["occlusion"] == "PARTIAL" and o["visibility_fraction"] is not None and not 0 < o["visibility_fraction"] < 1:
            bad("partial occlusion visibility contradiction")
        if o["occlusion"] == "NONE" and o["visibility_fraction"] not in (None, 1):
            bad("unoccluded visibility contradiction")
        if o["hand_id"] is not None:
            key = (o["session_id"], o["hand_id"])
            meta = (o["person_group_id"], o["side"])
            if key in hand_meta and hand_meta[key] != meta:
                bad("hand identity person/side changed")
            hand_meta[key] = meta
            if o["person_group_id"] is not None and o["person_group_id"] not in sessions[o["session_id"]]["person_group_ids"]:
                bad("hand person not declared in session")
    if errors:
        return errors  # Do not dereference invalid upstream scopes.

    def physical_pair(a, b, label):
        known = a["entity_kind"] == b["entity_kind"] == "REAL_HAND" and a["identity_status"] == b["identity_status"] == "VERIFIED"
        if label == "SAME_HAND" and not (known and a["hand_id"] == b["hand_id"]):
            bad("SAME_HAND needs verified matching physical identity")
        if label == "DIFFERENT_HAND" and not (known and a["hand_id"] != b["hand_id"]):
            bad("DIFFERENT_HAND needs verified distinct physical identities")
        if label == "REAL_VS_DEPICTED" and {a["entity_kind"], b["entity_kind"]} != {"REAL_HAND", "DEPICTED_HAND"}:
            bad("REAL_VS_DEPICTED contradiction")
    for g in gaps.values():
        a, b = hands.get(g["before_observation_id"]), hands.get(g["after_observation_id"])
        if not a or a["video_id"] != g["video_id"] or a["session_id"] != g["session_id"]:
            bad("gap anchor scope")
        if g["after_observation_id"] is not None:
            if not b or b["video_id"] != g["video_id"] or b["session_id"] != g["session_id"]:
                bad("gap return scope")
            elif a:
                if frames[a["frame_id"]]["sequence_index"] >= frames[b["frame_id"]]["sequence_index"]:
                    bad("gap return must follow anchor")
                if g["continuity"] in ("SAME_HAND", "REPLACEMENT"):
                    physical_pair(a, b, "SAME_HAND" if g["continuity"] == "SAME_HAND" else "DIFFERENT_HAND")
        if g["start_timestamp_ms"] is not None and g["end_timestamp_ms"] is not None and g["end_timestamp_ms"] <= g["start_timestamp_ms"]:
            bad("gap end must follow start")
    reid = bundle.get("reidentification", {"identity_links": [], "pairs": []})
    for collection, key in (("identity_links", "link_id"), ("pairs", "pair_id")):
        index(reid[collection], key)
        for pair in reid[collection]:
            g = gaps.get(pair["gap_id"])
            left = "before_observation_id" if collection == "identity_links" else "gallery_observation_id"
            right = "after_observation_id" if collection == "identity_links" else "query_observation_id"
            a, b = hands.get(pair[left]), hands.get(pair[right])
            if not g or not a or not b:
                bad("reidentification reference missing")
                continue
            if not (a["video_id"] == b["video_id"] == g["video_id"] and a["session_id"] == b["session_id"] == g["session_id"]):
                bad("reidentification must remain within session/video")
                continue
            fa, fb = frames[a["frame_id"]], frames[b["frame_id"]]
            if fa["sequence_index"] >= fb["sequence_index"]:
                bad("gallery must precede query")
            if collection == "identity_links" and (pair[left] != g["before_observation_id"] or pair[right] != g["after_observation_id"]):
                bad("identity link does not match gap endpoints")
            anchor, returned = hands.get(g["before_observation_id"]), hands.get(g["after_observation_id"])
            if anchor and fa["sequence_index"] > frames[anchor["frame_id"]]["sequence_index"]:
                bad("gallery leaks post-gap observation")
            if returned and fb["sequence_index"] < frames[returned["frame_id"]]["sequence_index"]:
                bad("query precedes gap return")
            physical_pair(a, b, pair["label"])
            if collection == "identity_links" and {"SAME_HAND": "SAME_HAND", "DIFFERENT_HAND": "REPLACEMENT", "UNKNOWN": "UNKNOWN"}[pair["label"]] != g["continuity"]:
                bad("identity link contradicts gap continuity")
    events = bundle["contact_events"]
    for e in events:
        v = videos.get(e["video_id"])
        if not v or v["session_id"] != e["session_id"]:
            bad("event video/session scope")
        start, end = e["start_timestamp_ms"], e["end_timestamp_ms"]
        if start is not None and end is not None and end <= start:
            bad("event end must follow start")
        if v and v["duration_ms"] is not None and end is not None and v["timestamp_basis"] == "VIDEO_PTS" and end > v["duration_ms"]:
            bad("event exceeds video duration")
        event_frames = []
        for field in ("start_frame_id", "end_frame_id"):
            if e[field] is not None:
                f = frames.get(e[field])
                if not f or f["video_id"] != e["video_id"]:
                    bad("event frame reference")
                else:
                    event_frames.append(f)
        if len(event_frames) == 2 and event_frames[0]["sequence_index"] > event_frames[1]["sequence_index"]:
            bad("event frame order")
        if e["scope"] == "SCENE" and e["hand_id"] is not None:
            bad("SCENE event cannot carry a specific physical hand_id")
        if e["scope"] == "HAND" and not e["observation_ids"]:
            bad("HAND event requires observation references")
        for oid in e["observation_ids"]:
            o = hands.get(oid)
            if not o or o["video_id"] != e["video_id"] or o["session_id"] != e["session_id"]:
                bad("event observation scope")
            elif e["label"] in ("TOUCH", "NEAR_NO_TOUCH") and o["entity_kind"] != "REAL_HAND":
                bad("depicted/unknown entity cannot verify physical contact")
            elif e["hand_id"] is not None and o["hand_id"] != e["hand_id"]:
                bad("event hand_id does not match observation")
        if e["hand_id"] is not None and (e["session_id"], e["hand_id"]) not in hand_meta:
            bad("event hand_id reference")
        if e["label"] in ("TOUCH", "NEAR_NO_TOUCH") and not e["observation_ids"]:
            bad("contact/near needs real-hand observation evidence")
        gt = e["ground_truth"]
        for source in gt["sources"]:
            if e["label"] != "UNKNOWN" and source["kind"] == "UNRESOLVED":
                bad("known contact label has unresolved source")
            if source["kind"] == "PRIMARY_VIDEO" and source["video_id"] != e["video_id"]:
                bad("ground truth primary video mismatch")
            if source["kind"] == "SIDE_REFERENCE":
                sync = syncs.get(source["sync_id"])
                if not sync or sync["video_id"] != e["video_id"] or sync["reference_id"] != source["reference_id"]:
                    bad("ground truth synchronization reference")
                elif e["label"] != "UNKNOWN" and sync["status"] != "MEASURED":
                    bad("verified side evidence needs measured synchronization")
    for i, a in enumerate(events):
        for b in events[i + 1:]:
            times = (a["start_timestamp_ms"], a["end_timestamp_ms"], b["start_timestamp_ms"], b["end_timestamp_ms"])
            if a["video_id"] != b["video_id"] or None in times or "UNKNOWN" in (a["label"], b["label"]):
                continue
            if max(times[0], times[2]) >= min(times[1], times[3]):
                continue
            same_scope = a["hand_id"] is not None and a["hand_id"] == b["hand_id"] or a["scope"] == b["scope"] == "SCENE"
            scene_no_touch = a["scope"] == "SCENE" and a["label"] == "NO_TOUCH" and b["label"] == "TOUCH" or b["scope"] == "SCENE" and b["label"] == "NO_TOUCH" and a["label"] == "TOUCH"
            if a["label"] != b["label"] and (same_scope or scene_no_touch):
                bad("contradictory overlapping contact intervals")
    return errors


def validate_bundle(bundle, require_real=False):
    errors = structural_errors(bundle)
    if errors:
        return errors
    errors = semantic_errors(bundle)
    if require_real and bundle["data_kind"] != "REAL_CAPTURE":
        errors.append("SYNTHETIC_TEST is ineligible for real AI evaluation")
    return errors


def validation_report(bundle, require_real=False):
    errors = validate_bundle(bundle, require_real)
    formal = "NOT_AVAILABLE"
    formal_errors = []
    if importlib.util.find_spec("jsonschema") is not None:
        from jsonschema import Draft7Validator
        schema = load_json(SCHEMA_PATH)
        Draft7Validator.check_schema(schema)
        formal_errors = [str(e) for e in Draft7Validator(schema).iter_errors(bundle)]
        formal = "PASS" if not formal_errors else "FAIL"
    return {"authored_schema_subset_and_semantics": "FAIL" if errors else "PASS",
            "errors": errors, "formal_draft7": formal, "formal_errors": formal_errors,
            "data_kind": bundle.get("data_kind") if isinstance(bundle, dict) else None,
            "ai_metrics": "NOT_EVALUATED", "evaluation_readiness": "NOT_CERTIFIED"}


def asset_errors(bundle, asset_root):
    """Optional explicit read-only asset check, never invoked by unit fixtures."""
    root = Path(asset_root).resolve()
    rows = [(v["relative_path"], v["sha256"]) for v in bundle["videos"] + bundle["reference_videos"]]
    rows += [(f["raw_image_path"], f["raw_image_sha256"]) for f in bundle["frames"] if f["frame_status"] == "OK"]
    errors = []
    for name, expected in rows:
        path = (root / name).resolve()
        try:
            path.relative_to(root)
        except ValueError:
            errors.append("asset escapes root: " + name)
            continue
        if not path.is_file():
            errors.append("asset missing: " + name)
            continue
        digest = hashlib.sha256()
        with path.open("rb") as inp:
            for chunk in iter(lambda: inp.read(1024 * 1024), b""):
                digest.update(chunk)
        if digest.hexdigest() != expected:
            errors.append("asset hash mismatch: " + name)
    return errors


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("bundle")
    parser.add_argument("--require-real", action="store_true")
    parser.add_argument("--asset-root", help="Optional explicit read-only media/hash checks")
    args = parser.parse_args()
    try:
        bundle = load_json(args.bundle)
        report = validation_report(bundle, args.require_real)
        if args.asset_root and not report["errors"]:
            report["asset_errors"] = asset_errors(bundle, args.asset_root)
        print(json.dumps(report, ensure_ascii=True, indent=2))
        return 1 if report["errors"] or report["formal_errors"] or report.get("asset_errors") else 0
    except (ValueError, OSError, KeyError) as exc:
        print(json.dumps({"status": "FAIL", "error": str(exc)}, ensure_ascii=True))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
