"""Inspect the original Pascal VOC ContactHands format without changing source data."""

import argparse
import json
import math
import os
import struct
import sys
import xml.etree.ElementTree as ET
from collections import Counter
from pathlib import Path

CONTACT_LABELS = ("No-Contact", "Self-Contact", "Other-Person-Contact", "Object-Contact")
UNSURE_VALUE = 2
SPLITS = ("train", "test", "sub")


def read_image_dimensions(path):
    """Read JPEG/PNG dimensions using only the standard library."""
    path = Path(path)
    with path.open("rb") as image:
        header = image.read(24)
        if header.startswith(b"\x89PNG\r\n\x1a\n") and header[12:16] == b"IHDR":
            width, height = struct.unpack(">II", header[16:24])
            return width, height
        if header[:3] != b"\xff\xd8\xff":
            raise ValueError("unsupported or invalid image signature (expected JPEG or PNG)")
        image.seek(2)
        while True:
            prefix = image.read(1)
            if not prefix:
                break
            if prefix != b"\xff":
                continue
            marker = image.read(1)
            while marker == b"\xff":
                marker = image.read(1)
            if not marker or marker in (b"\xd8", b"\xd9", b"\x01"):
                if marker == b"\xd9":
                    break
                continue
            marker_code = marker[0]
            if 0xD0 <= marker_code <= 0xD7:
                continue
            length_data = image.read(2)
            if len(length_data) != 2:
                break
            segment_length = struct.unpack(">H", length_data)[0]
            if segment_length < 2:
                break
            if marker_code in (0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7,
                               0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF):
                frame = image.read(5)
                if len(frame) != 5:
                    break
                height, width = struct.unpack(">HH", frame[1:5])
                return width, height
            image.seek(segment_length - 2, os.SEEK_CUR)
    raise ValueError("could not read image dimensions")


def _text(parent, path):
    element = parent.find(path)
    return element.text.strip() if element is not None and element.text else None


def parse_voc_annotation(annotation_path):
    """Return dimensions and validated hand records from one ContactHands XML."""
    tree = ET.parse(str(annotation_path))
    root = tree.getroot()
    width_text, height_text = _text(root, "size/width"), _text(root, "size/height")
    if not width_text or not height_text:
        raise ValueError("missing image width/height in XML")
    width, height = int(width_text), int(height_text)
    if width <= 0 or height <= 0:
        raise ValueError("image dimensions must be positive")
    annotations = []
    for index, obj in enumerate(root.findall("object")):
        class_name = _text(obj, "name")
        if not class_name:
            raise ValueError("object {} has no class name".format(index))
        box = obj.find("bndbox")
        if box is None:
            raise ValueError("object {} has no bndbox".format(index))
        try:
            coordinates = [float(_text(box, name)) for name in ("xmin", "ymin", "xmax", "ymax")]
        except (TypeError, ValueError):
            raise ValueError("object {} has invalid XYXY box".format(index))
        if any(not math.isfinite(value) for value in coordinates):
            raise ValueError("object {} has non-finite box coordinate".format(index))
        x1, y1, x2, y2 = coordinates
        if x1 < 1 or y1 < 1 or x2 > width or y2 > height or x1 >= x2 or y1 >= y2:
            raise ValueError("object {} has invalid/out-of-image VOC box".format(index))
        raw_state = _text(obj, "contact_state")
        if raw_state is None:
            raise ValueError("object {} has no contact_state".format(index))
        try:
            state_parts = raw_state.split(",")
            if len(state_parts) != 4:
                raise ValueError("expected four values")
            state = [float(value.strip()) for value in state_parts]
        except ValueError:
            raise ValueError("object {} has invalid contact_state values".format(index))
        if len(state) != 4 or any(value not in (0.0, 1.0, float(UNSURE_VALUE)) for value in state):
            raise ValueError("object {} contact_state must have four 0/1/2 values".format(index))
        polygon = []
        try:
            polygon = [(float(_text(box, "x{}".format(i))),
                        float(_text(box, "y{}".format(i)))) for i in range(1, 5)]
        except (TypeError, ValueError):
            raise ValueError("object {} is missing the four ContactHands mask points".format(index))
        if any(not math.isfinite(value) for point in polygon for value in point):
            raise ValueError("object {} has non-finite polygon coordinate".format(index))
        if class_name != "hand":
            raise ValueError("unsupported ContactHands class {!r}; expected 'hand'".format(class_name))
        annotations.append({"bbox_voc_xyxy": coordinates, "contact_state": state,
                            "segmentation_polygon": polygon})
    return {"width": width, "height": height, "annotations": annotations}


def validate_dataset(root):
    """Check split lists, images, XML annotations and image/XML dimensions."""
    root = Path(root).expanduser()
    report = {
        "root": str(root.resolve()), "format": "ContactHands Pascal VOC",
        "splits": {}, "image_count": 0, "hand_annotation_count": 0,
        "contact_label_counts": {
            label: {"positive": 0, "negative": 0, "unsure": 0} for label in CONTACT_LABELS
        },
        "issues": [],
    }

    def issue(severity, code, path, message):
        report["issues"].append({"severity": severity, "code": code,
                                 "path": str(path), "message": message})

    def finish():
        report["error_count"] = sum(item["severity"] == "ERROR" for item in report["issues"])
        report["warning_count"] = sum(item["severity"] == "WARNING" for item in report["issues"])
        return report

    split_dir = root / "ImageSets" / "Main"
    existing_splits = [name for name in SPLITS if (split_dir / (name + ".txt")).is_file()]
    if not root.is_dir():
        issue("ERROR", "DATASET_MISSING", root, "Dataset directory does not exist")
        return finish()
    if not existing_splits:
        issue("ERROR", "SPLITS_MISSING", split_dir, "No train.txt, test.txt, or sub.txt split file found")
        return finish()

    seen = set()
    ids_seen_in_any_split = {}
    for split in existing_splits:
        split_file = split_dir / (split + ".txt")
        ids = [line.strip() for line in split_file.read_text(encoding="utf-8-sig").splitlines()
               if line.strip() and not line.lstrip().startswith("#")]
        report["splits"][split] = {"listed_images": len(ids)}
        for image_id in ids:
            split_key = (split, image_id)
            if split_key in seen:
                issue("WARNING", "DUPLICATE_ID", split_file, "Duplicate image id {}".format(image_id))
                continue
            seen.add(split_key)
            if image_id in ids_seen_in_any_split:
                issue("WARNING", "SPLIT_OVERLAP", split_file,
                      "Image id {} also appears in {}".format(image_id, ids_seen_in_any_split[image_id]))
                continue
            ids_seen_in_any_split[image_id] = split
            annotation_path = root / "Annotations" / (image_id + ".xml")
            image_path = root / "JPEGImages" / (image_id + ".jpg")
            missing = False
            if not annotation_path.is_file():
                issue("ERROR", "ANNOTATION_MISSING", annotation_path, "Annotation XML does not exist")
                missing = True
            if not image_path.is_file():
                issue("ERROR", "IMAGE_MISSING", image_path, "Expected image file does not exist")
                missing = True
            if missing:
                continue
            try:
                annotation = parse_voc_annotation(annotation_path)
            except (ET.ParseError, OSError, ValueError) as error:
                issue("ERROR", "ANNOTATION_INVALID", annotation_path, str(error))
                continue
            try:
                actual_width, actual_height = read_image_dimensions(image_path)
            except (OSError, ValueError) as error:
                issue("ERROR", "IMAGE_INVALID", image_path, str(error))
                continue
            if (actual_width, actual_height) != (annotation["width"], annotation["height"]):
                issue("ERROR", "DIMENSION_MISMATCH", annotation_path,
                      "XML is {}x{}; image is {}x{}".format(
                          annotation["width"], annotation["height"], actual_width, actual_height))
                continue
            report["image_count"] += 1
            report["hand_annotation_count"] += len(annotation["annotations"])
            for hand in annotation["annotations"]:
                for label, value in zip(CONTACT_LABELS, hand["contact_state"]):
                    if value == 1:
                        report["contact_label_counts"][label]["positive"] += 1
                    elif value == 0:
                        report["contact_label_counts"][label]["negative"] += 1
                    elif value == UNSURE_VALUE:
                        report["contact_label_counts"][label]["unsure"] += 1
    return finish()


def preview_annotations(root, output_dir, split="test", limit=12):
    try:
        import cv2
    except ImportError as error:
        raise RuntimeError("preview requires OpenCV in the active environment: {}".format(error))
    root, output_dir = Path(root), Path(output_dir)
    split_file = root / "ImageSets" / "Main" / (split + ".txt")
    ids = [line.strip() for line in split_file.read_text(encoding="utf-8-sig").splitlines()
           if line.strip() and not line.lstrip().startswith("#")][:max(0, int(limit))]
    output_dir.mkdir(parents=True, exist_ok=True)
    outputs = []
    palette = ((255, 255, 0), (255, 0, 255), (0, 0, 255), (0, 255, 255))
    for image_id in ids:
        image_path = root / "JPEGImages" / (image_id + ".jpg")
        xml_path = root / "Annotations" / (image_id + ".xml")
        image = cv2.imread(str(image_path))
        if image is None:
            raise ValueError("could not read {}".format(image_path))
        data = parse_voc_annotation(xml_path)
        for hand in data["annotations"]:
            x1, y1, x2, y2 = hand["bbox_voc_xyxy"]
            cv2.rectangle(image, (int(x1), int(y1)), (int(x2), int(y2)), (0, 255, 255), 2)
            active = ["{}={}".format(CONTACT_LABELS[i], "unsure" if value == 2 else "yes")
                      for i, value in enumerate(hand["contact_state"]) if value in (1, 2)]
            cv2.putText(image, ", ".join(active) or "No contact",
                        (max(0, int(x1)), max(15, int(y1) - 5)),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 2, cv2.LINE_AA)
            polygon = hand["segmentation_polygon"]
            for i, point in enumerate(polygon):
                cv2.circle(image, (int(point[0]), int(point[1])), 3, palette[i], -1)
        output = output_dir / (image_id + "_annotation_preview.jpg")
        if not cv2.imwrite(str(output), image):
            raise OSError("could not write preview {}".format(output))
        outputs.append(str(output))
    return outputs


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command")
    for name in ("validate", "stats"):
        command = sub.add_parser(name, help="validate files and print actual dataset statistics")
        command.add_argument("--root", required=True, help="ContactHands Pascal VOC dataset root")
        command.add_argument("--json", action="store_true", help="print machine-readable JSON")
    preview = sub.add_parser("preview", help="render actual annotations over source images")
    preview.add_argument("--root", required=True)
    preview.add_argument("--split", choices=SPLITS, default="test")
    preview.add_argument("--limit", type=int, default=12)
    preview.add_argument("--output-dir", required=True)
    args = parser.parse_args(argv)
    if args.command in ("validate", "stats"):
        report = validate_dataset(args.root)
        if args.json:
            print(json.dumps(report, indent=2, ensure_ascii=False))
        else:
            print("Dataset: {}".format(report["root"]))
            print("Images read: {}; hand annotations: {}".format(
                report["image_count"], report["hand_annotation_count"]))
            for split, values in report["splits"].items():
                print("{}: {} listed".format(split, values["listed_images"]))
            for label, values in report["contact_label_counts"].items():
                print("{}: {} positive, {} negative, {} unsure".format(
                    label, values["positive"], values["negative"], values["unsure"]))
            for item in report["issues"]:
                print("{} {}: {} ({})".format(item["severity"], item["code"], item["message"], item["path"]))
            print("{} errors; {} warnings".format(report.get("error_count", 0), report.get("warning_count", 0)))
        return 1 if report.get("error_count", 0) else 0
    if args.command == "preview":
        outputs = preview_annotations(args.root, args.output_dir, args.split, args.limit)
        for path in outputs:
            print(path)
        return 0
    parser.print_help()
    return 2


if __name__ == "__main__":
    sys.exit(main())

