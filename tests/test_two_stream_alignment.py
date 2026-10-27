"""Tests for two-stream coordinate alignment during ContactHands training.

The original train_net.py re-reads the image from disk for stream 2
(cv2.imread + cv2.resize) while the mapper applies RandomFlip to stream 1.
These tests need torch, OpenCV and detectron2: run them in the WSL 'contacthands'
environment. They are skipped when those packages cannot be imported.
"""

import sys
import tempfile
import unittest
from pathlib import Path

import numpy as np

SRC_ROOT = Path(__file__).resolve().parents[1] / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

STACK_ERROR = ""
try:
    import cv2
    import torch
    from PIL import Image
    from detectron2.config import get_cfg
    from detectron2.data import transforms as T
    from detectron2.structures import BoxMode
    from contact_hands_two_stream.data.dataset_mapper import CustomDatasetMapper
    HAVE_STACK = True
except Exception as error:  # depends on the interpreter
    HAVE_STACK = False
    STACK_ERROR = repr(error)

HELPER = "contact_hands_two_stream.engine.second_stream_alignment"
WIDTH, HEIGHT = 200, 120
SQUARE = (20, 50, 40, 70)  # x1, y1, x2, y2 in the original image


def make_image(path):
    pixels = np.zeros((HEIGHT, WIDTH, 3), dtype=np.uint8)
    x1, y1, x2, y2 = SQUARE
    pixels[y1:y2, x1:x2] = 255
    Image.fromarray(pixels).save(str(path))


def box_of_bright_pixels(image_bgr):
    mask = image_bgr.max(axis=2) > 128
    ys, xs = np.where(mask)
    return [float(xs.min()), float(ys.min()), float(xs.max() + 1), float(ys.max() + 1)]


class FakeStream2:
    """Stands in for CustomPredictor: returns the box of the bright pixels it sees."""

    def __call__(self, image_bgr):
        return [torch.tensor([box_of_bright_pixels(image_bgr)])]


def iou(a, b):
    x1, y1 = max(a[0], b[0]), max(a[1], b[1])
    x2, y2 = min(a[2], b[2]), min(a[3], b[3])
    inter = max(0.0, x2 - x1) * max(0.0, y2 - y1)
    area_a = (a[2] - a[0]) * (a[3] - a[1])
    area_b = (b[2] - b[0]) * (b[3] - b[1])
    union = area_a + area_b - inter
    return inter / union if union > 0 else 0.0


def run_mapper(path, min_size, flip):
    cfg = get_cfg()
    cfg.INPUT.MIN_SIZE_TRAIN = (min_size,)
    cfg.INPUT.MAX_SIZE_TRAIN = 1000
    mapper = CustomDatasetMapper(cfg, is_train=True)
    gens = [T.ResizeShortestEdge((min_size,), 1000, "choice")]
    if flip:
        gens.append(T.RandomFlip(prob=1.0))
    mapper.tfm_gens = gens
    record = {
        "file_name": str(path), "image_id": "synthetic",
        "width": WIDTH, "height": HEIGHT,
        "annotations": [{"bbox": [float(v) for v in SQUARE],
                         "bbox_mode": BoxMode.XYXY_ABS, "category_id": 0,
                         "cats": [0.0, 0.0, 0.0, 1.0]}],
    }
    return mapper(record)


def legacy_stream2(model2, image_path, mapper_image):
    """Mirror of train_net.py lines 60-64 (inference_second_stream)."""
    height = mapper_image.shape[1]
    width = mapper_image.shape[2]
    im = cv2.imread(str(image_path))
    im = cv2.resize(im, (width, height))
    return model2(im)


@unittest.skipUnless(HAVE_STACK, "needs torch/OpenCV/detectron2: {}".format(STACK_ERROR))
class TwoStreamAlignmentTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.path = Path(self.directory.name) / "scene.png"
        make_image(self.path)

    def tearDown(self):
        self.directory.cleanup()

    def hand_box(self, out):
        return out["instances"].gt_boxes.tensor[0].tolist()

    # --- documents the behaviour of the original train_net.py ---
    def test_legacy_train_net_is_misaligned_when_flip_happens(self):
        out = run_mapper(self.path, 120, flip=True)
        objects = legacy_stream2(FakeStream2(), self.path, out["image"])
        self.assertLess(iou(self.hand_box(out), objects[0][0].tolist()), 0.1)

    def test_legacy_train_net_matches_when_no_flip(self):
        out = run_mapper(self.path, 120, flip=False)
        objects = legacy_stream2(FakeStream2(), self.path, out["image"])
        self.assertGreater(iou(self.hand_box(out), objects[0][0].tolist()), 0.85)

    # --- behaviour required from the fix ---
    def aligned(self, data):
        from importlib import import_module
        helper = import_module(HELPER)
        return helper.inference_second_stream_aligned(FakeStream2(), data)

    def test_aligned_stream2_matches_stream1_with_flip(self):
        out = run_mapper(self.path, 120, flip=True)
        objects = self.aligned([out])
        self.assertGreater(iou(self.hand_box(out), objects[0][0].tolist()), 0.85)

    def test_aligned_stream2_matches_stream1_without_flip(self):
        out = run_mapper(self.path, 120, flip=False)
        objects = self.aligned([out])
        self.assertGreater(iou(self.hand_box(out), objects[0][0].tolist()), 0.85)

    def test_aligned_stream2_matches_stream1_with_resize_and_flip(self):
        out = run_mapper(self.path, 240, flip=True)
        objects = self.aligned([out])
        self.assertGreater(iou(self.hand_box(out), objects[0][0].tolist()), 0.85)

    def test_rgb_format_is_converted_to_bgr_hwc(self):
        from importlib import import_module
        helper = import_module(HELPER)
        tensor = torch.zeros((3, 2, 2), dtype=torch.uint8)
        tensor[0], tensor[1], tensor[2] = 10, 20, 30
        bgr = helper.mapper_image_to_bgr_hwc(tensor, "BGR")
        rgb = helper.mapper_image_to_bgr_hwc(tensor, "RGB")
        self.assertEqual(bgr[0, 0].tolist(), [10, 20, 30])
        self.assertEqual(rgb[0, 0].tolist(), [30, 20, 10])
        self.assertTrue(rgb.flags["C_CONTIGUOUS"])

    def test_batch_size_other_than_one_is_rejected(self):
        out = run_mapper(self.path, 120, flip=False)
        with self.assertRaises(ValueError):
            self.aligned([out, out])


if __name__ == "__main__":
    unittest.main()