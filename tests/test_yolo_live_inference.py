from pathlib import Path

from ultralytics import YOLO


def test_yolo_segmentation_model_can_load():
    model = YOLO("yolov8n-seg.pt")
    assert model is not None
    assert Path(model.ckpt_path).name == "yolov8n-seg.pt" or model.ckpt_path is not None


def test_yolo_pipeline_model_name_defaults_are_valid():
    from src.yolo_pipeline import DEFAULT_YOLO_MODEL

    assert DEFAULT_YOLO_MODEL == "yolov8n-seg.pt"
