from __future__ import annotations

import argparse
import hashlib
import json
import random
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
DATASET = ROOT / "dataset"
MET_MANIFEST = DATASET / "public/metmuseum/metadata/met_artworks_manifest.json"
SYNTHETIC_ROOT = DATASET / "synthetic/art_contact"
WIDTH, HEIGHT = 640, 360


def read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def write_image(path: Path, image: np.ndarray, params: list[int] | None = None) -> None:
    encoded, buffer = cv2.imencode(path.suffix or ".jpg", image, params or [])
    if not encoded:
        raise RuntimeError(f"Could not encode image: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(buffer.tobytes())


def load_artworks() -> list[dict]:
    if not MET_MANIFEST.is_file():
        raise FileNotFoundError(
            f"No verified Met Open Access assets found at {MET_MANIFEST}. "
            "Run `python tools/dataset_acquire.py metmuseum-artworks` first."
        )
    manifest = read_json(MET_MANIFEST)
    assets = []
    for item in manifest.get("objects", []):
        image_path = ROOT / item["path"]
        if item.get("license") != "CC0 1.0 (Open Access public-domain record)":
            raise ValueError(f"Refusing non-CC0 artwork asset {item.get('object_id')}.")
        if not image_path.is_file() or sha256(image_path) != item.get("sha256"):
            raise ValueError(f"Missing or changed Met artwork asset: {image_path}")
        image = cv2.imdecode(np.fromfile(image_path, dtype=np.uint8), cv2.IMREAD_COLOR)
        if image is None or image.size == 0:
            raise ValueError(f"Invalid Met artwork image: {image_path}")
        assets.append({**item, "image_path": image_path, "image": image})
    if not assets:
        raise ValueError("The Met manifest has no validated public-domain painting images.")
    return assets


def _wall(rng: random.Random) -> np.ndarray:
    """Create an intentionally flat, stylized synthetic backdrop, not a gallery photograph."""
    base = np.asarray((222, 225, 228), dtype=np.uint8)
    canvas = np.empty((HEIGHT, WIDTH, 3), dtype=np.uint8)
    canvas[:] = base
    tint = rng.randint(-7, 7)
    canvas[:] = np.clip(base.astype(np.int16) + tint, 0, 255).astype(np.uint8)
    cv2.rectangle(canvas, (0, 310), (WIDTH - 1, HEIGHT - 1), (190, 194, 198), -1)
    cv2.line(canvas, (0, 310), (WIDTH - 1, 310), (150, 154, 159), 3)
    return canvas


def _artwork_layer(canvas: np.ndarray, artwork: np.ndarray, rng: random.Random) -> np.ndarray:
    left = rng.randint(350, 374)
    top = rng.randint(62, 94)
    art_width = rng.randint(170, 204)
    art_height = rng.randint(146, 190)
    tilt = rng.randint(-9, 9)
    inner = np.asarray(
        [[left, top], [left + art_width, top], [left + art_width - tilt, top + art_height], [left + tilt, top + art_height]],
        dtype=np.int32,
    )
    outer = np.asarray(
        [[left - 9, top - 9], [left + art_width + 9, top - 9], [left + art_width - tilt + 9, top + art_height + 9], [left + tilt - 9, top + art_height + 9]],
        dtype=np.int32,
    )
    cv2.fillPoly(canvas, [outer], (91, 72, 51))
    cv2.polylines(canvas, [inner], True, (166, 136, 91), 3)

    resized = cv2.resize(artwork, (art_width, art_height), interpolation=cv2.INTER_AREA)
    source_corners = np.asarray(
        [[0, 0], [art_width - 1, 0], [art_width - 1, art_height - 1], [0, art_height - 1]], dtype=np.float32
    )
    destination_corners = (inner.astype(np.float32) - np.asarray([[0, 0], [1, 0], [1, 1], [0, 1]], dtype=np.float32))
    transform = cv2.getPerspectiveTransform(source_corners, destination_corners)
    warped_art = cv2.warpPerspective(resized, transform, (WIDTH, HEIGHT), flags=cv2.INTER_LINEAR)
    source_mask = np.full((art_height, art_width), 255, dtype=np.uint8)
    mask = cv2.warpPerspective(source_mask, transform, (WIDTH, HEIGHT), flags=cv2.INTER_NEAREST)
    canvas[mask > 0] = warped_art[mask > 0]
    return mask


def _hand_mask(event: str, rng: random.Random, art_box: tuple[float, float, float, float]) -> np.ndarray:
    """Draw a high-contrast vector glove silhouette with exact synthetic pixels."""
    local = np.zeros((82, 112), dtype=np.uint8)
    palm_and_fingers = np.asarray(
        [[5, 39], [19, 32], [29, 22], [34, 6], [41, 4], [45, 27],
         [53, 7], [61, 6], [62, 29], [73, 13], [81, 16], [75, 35],
         [93, 26], [102, 31], [89, 44], [67, 58], [55, 73], [20, 74], [8, 61]],
        dtype=np.int32,
    )
    cv2.fillPoly(local, [palm_and_fingers], 255)
    cv2.circle(local, (34, 44), 15, 255, -1)
    angle = rng.uniform(-4.0, 4.0)
    scale = rng.uniform(0.9, 1.12)
    matrix = cv2.getRotationMatrix2D((56, 41), angle, scale)
    rotated = cv2.warpAffine(local, matrix, (112, 82), flags=cv2.INTER_NEAREST)
    if event == "SAFE":
        x, y = rng.randint(40, 160), rng.randint(150, 255)
    elif event == "NEAR":
        x = int(art_box[0]) - 112 - rng.randint(4, 14)
        y = int((art_box[1] + art_box[3]) / 2) - 41 + rng.randint(-8, 8)
    else:
        x = int(art_box[0]) - 88 + rng.randint(0, 18)
        y = int((art_box[1] + art_box[3]) / 2) - 41 + rng.randint(-8, 8)
    output = np.zeros((HEIGHT, WIDTH), dtype=np.uint8)
    height = min(rotated.shape[0], HEIGHT - y)
    width = min(rotated.shape[1], WIDTH - x)
    output[y:y + height, x:x + width] = rotated[:height, :width]
    return output


def _tool_mask(event: str, rng: random.Random, art_box: tuple[float, float, float, float]) -> np.ndarray:
    """Draw a stylized paintbrush as exact mask geometry; this is not a real cutout."""
    output = np.zeros((HEIGHT, WIDTH), dtype=np.uint8)
    length = rng.randint(78, 104)
    if event == "SAFE":
        center = (rng.randint(90, 190), rng.randint(155, 245))
    elif event == "NEAR":
        center = (int(art_box[0]) - length - rng.randint(8, 18), int((art_box[1] + art_box[3]) / 2))
    else:
        center = (int(art_box[0]) - length + rng.randint(8, 24), int((art_box[1] + art_box[3]) / 2))
    angle = np.deg2rad(rng.uniform(-4, 4))
    end = (int(round(center[0] + length * np.cos(angle))), int(round(center[1] + length * np.sin(angle))))
    cv2.line(output, center, end, 255, 9, cv2.LINE_8)
    cv2.circle(output, center, 6, 255, -1)
    return output


def _box(mask: np.ndarray) -> tuple[float, float, float, float]:
    ys, xs = np.where(mask > 0)
    if len(xs) == 0:
        raise ValueError("Synthetic interaction mask is empty")
    return float(xs.min()), float(ys.min()), float(xs.max() + 1), float(ys.max() + 1)


def _validate_geometry(event: str, art_mask: np.ndarray, interaction_mask: np.ndarray) -> dict:
    overlap_pixels = int(np.count_nonzero((art_mask > 0) & (interaction_mask > 0)))
    hand_box = _box(interaction_mask)
    art_box = _box(art_mask)
    gap_x = max(hand_box[0] - art_box[2], art_box[0] - hand_box[2], 0.0)
    gap_y = max(hand_box[1] - art_box[3], art_box[1] - hand_box[3], 0.0)
    gap = float(np.hypot(gap_x, gap_y))
    expected = {
        "CONTACT": overlap_pixels > 0,
        "NEAR": overlap_pixels == 0 and gap <= 30.0,
        "SAFE": overlap_pixels == 0 and gap > 30.0,
    }[event]
    if not expected:
        raise ValueError(f"Generated {event} geometry failed its mask-overlap/gap check: overlap={overlap_pixels}, gap={gap:.1f}")
    return {"overlap_pixels": overlap_pixels, "box_gap_pixels": round(gap, 3)}


def _draw_interaction(canvas: np.ndarray, interaction_mask: np.ndarray, class_name: str) -> None:
    if class_name == "hand":
        color = (215, 110, 25)
    else:
        color = (20, 95, 215)
    canvas[interaction_mask > 0] = color


def _split_art_groups(artworks: list[dict], seed: int) -> dict[str, str]:
    groups = [str(item["object_id"]) for item in artworks]
    random.Random(seed).shuffle(groups)
    assignments: dict[str, str] = {}
    for index, group in enumerate(groups):
        if len(groups) < 3:
            split = "train"
        elif index == len(groups) - 1:
            split = "test"
        elif index == len(groups) - 2:
            split = "val"
        else:
            split = "train"
        assignments[group] = split
    return assignments


def generate(per_scenario: int = 2, seed: int = 42) -> dict:
    if per_scenario <= 0:
        raise ValueError("per_scenario must be positive")
    artworks = load_artworks()
    for directory in (SYNTHETIC_ROOT / "images", SYNTHETIC_ROOT / "masks", SYNTHETIC_ROOT / "metadata"):
        directory.mkdir(parents=True, exist_ok=True)
    assignments = _split_art_groups(artworks, seed)
    rng = random.Random(seed)
    samples = []
    sample_index = 0
    for artwork in artworks:
        for event in ("SAFE", "NEAR", "CONTACT"):
            for variation in range(per_scenario):
                local_seed = seed + sample_index * 104729
                scene_rng = random.Random(local_seed)
                canvas = _wall(scene_rng)
                art_mask = _artwork_layer(canvas, artwork["image"], scene_rng)
                art_box = _box(art_mask)
                interaction_class = "hand" if (variation + sample_index) % 2 == 0 else "tool"
                interaction_mask = _hand_mask(event, scene_rng, art_box) if interaction_class == "hand" else _tool_mask(event, scene_rng, art_box)
                geometry = _validate_geometry(event, art_mask, interaction_mask)
                _draw_interaction(canvas, interaction_mask, interaction_class)

                stem = f"seed_{seed:05d}_scene_{sample_index:06d}"
                image_path = SYNTHETIC_ROOT / "images" / f"{stem}.jpg"
                image_params = [cv2.IMWRITE_JPEG_QUALITY, 95]
                if image_path.exists():
                    encoded, buffer = cv2.imencode(".jpg", canvas, image_params)
                    if not encoded or hashlib.sha256(buffer.tobytes()).hexdigest() != sha256(image_path):
                        raise FileExistsError(f"Existing synthetic sample differs from this deterministic run: {image_path}")
                else:
                    write_image(image_path, canvas, image_params)
                mask_rows = {}
                for class_name, mask in (("painting", art_mask), (interaction_class, interaction_mask)):
                    mask_path = SYNTHETIC_ROOT / "masks" / f"{stem}_{class_name}.png"
                    if mask_path.exists():
                        encoded, buffer = cv2.imencode(".png", mask)
                        if not encoded or hashlib.sha256(buffer.tobytes()).hexdigest() != sha256(mask_path):
                            raise FileExistsError(f"Existing synthetic mask differs from this deterministic run: {mask_path}")
                    else:
                        write_image(mask_path, mask)
                    mask_rows[class_name] = {
                        "path": mask_path.relative_to(ROOT).as_posix(),
                        "pixels": int(np.count_nonzero(mask)),
                        "sha256": sha256(mask_path),
                    }
                decoded = cv2.imdecode(np.fromfile(image_path, dtype=np.uint8), cv2.IMREAD_COLOR)
                if decoded is None or decoded.shape[:2] != (HEIGHT, WIDTH):
                    raise ValueError(f"Generated image failed decode/dimensions check: {image_path}")
                sample = {
                    "sample_id": stem,
                    "sample_type": "SYNTHETIC",
                    "source_group_id": f"met-object-{artwork['object_id']}",
                    "split": assignments[str(artwork["object_id"])],
                    "source_artwork": {
                        "object_id": artwork["object_id"],
                        "title": artwork["title"],
                        "artist": artwork["artist"],
                        "object_url": artwork["object_url"],
                        "license": artwork["license"],
                        "license_url": artwork["license_url"],
                        "sha256": artwork["sha256"],
                        "artwork_boundary_annotation": "The original art image is warped into a quadrilateral; its pixels define the artwork-image region, not a gallery/frame-scene annotation.",
                    },
                    "background": "SYNTHETIC flat vector wall; not a photograph",
                    "interaction_shape": f"SYNTHETIC vector {interaction_class}; not a real cutout mask",
                    "event_label": event,
                    "event_label_source": "SYNTHETIC geometry label; not real-world ground truth",
                    "image_path": image_path.relative_to(ROOT).as_posix(),
                    "image_sha256": sha256(image_path),
                    "masks": mask_rows,
                    "geometry_validation": geometry,
                    "random_seed": local_seed,
                }
                samples.append(sample)
                sample_index += 1

    manifest_path = SYNTHETIC_ROOT / "metadata/synthetic_manifest.jsonl"
    if manifest_path.exists():
        raise FileExistsError(f"Refusing to overwrite synthetic manifest: {manifest_path}")
    manifest_path.write_text("".join(json.dumps(sample, ensure_ascii=False) + "\n" for sample in samples), encoding="utf-8")
    counts = Counter(sample["event_label"] for sample in samples)
    splits: dict[str, set[str]] = defaultdict(set)
    for sample in samples:
        splits[sample["split"]].add(sample["source_group_id"])
    report = {
        "sample_type": "SYNTHETIC",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "seed": seed,
        "artwork_sources": len(artworks),
        "images": len(samples),
        "masks": sum(len(sample["masks"]) for sample in samples),
        "events": dict(counts),
        "images_by_split": {split: sum(sample["split"] == split for sample in samples) for split in ("train", "val", "test")},
        "artwork_source_groups_by_split": {split: sorted(splits.get(split, set())) for split in ("train", "val", "test")},
        "source_group_leakage": any(
            bool(splits[left] & splits[right]) for left, right in (("train", "val"), ("train", "test"), ("val", "test"))
        ),
        "real_hand_cutouts_used": 0,
        "real_gallery_backgrounds_used": 0,
        "training_ready_for_real_world_claims": False,
        "limitations": [
            "Hand/tool shapes and wall are explicit vector synthetic assets, not real cutouts or gallery photographs.",
            "The artwork crop boundary is valid only for this synthetic artwork-image-region task.",
            "Do not use synthetic-only metrics as real-world accuracy or artwork-contact validation.",
        ],
        "manifest": manifest_path.relative_to(ROOT).as_posix(),
    }
    report_path = SYNTHETIC_ROOT / "metadata/synthetic_report.json"
    report_path.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate deterministic, clearly labeled synthetic artwork-contact scenes.")
    parser.add_argument("--per-scenario", type=int, default=2, help="Variants per SAFE/NEAR/CONTACT class for each CC0 artwork.")
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()
    try:
        result = generate(args.per_scenario, args.seed)
        print(json.dumps(result, indent=2, ensure_ascii=False))
    except Exception as exc:
        print(f"Synthetic generation failed: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

