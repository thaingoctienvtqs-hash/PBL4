import random
import cv2
import os
import argparse
from pathlib import Path
import numpy as np 
import torch
from detectron2.config import get_cfg
from contact_hands_two_stream import CustomVisualizer
from detectron2.data import MetadataCatalog
from contact_hands_two_stream import add_contacthands_config
from datasets import load_voc_hand_instances, register_pascal_voc
from contact_hands_two_stream.engine import CustomPredictor
from detectron2.modeling import build_model
from detectron2.data import MetadataCatalog
from detectron2.checkpoint import DetectionCheckpointer, PeriodicCheckpointer

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SECOND_STREAM_URI = (
    "detectron2://COCO-InstanceSegmentation/mask_rcnn_R_101_FPN_3x/"
    "138205316/model_final_a3ec72.pkl"
)
DEFAULT_SECOND_STREAM_CACHE = (
    Path.home() / ".torch" / "iopath_cache" / "detectron2" /
    "COCO-InstanceSegmentation" / "mask_rcnn_R_101_FPN_3x" /
    "138205316" / "model_final_a3ec72.pkl"
)


class CustomPredictorTwoStream:

    def __init__(self, cfg):
        self.cfg = cfg.clone()  
        self.model = build_model(self.cfg)
        self.model.eval()
        self.metadata = MetadataCatalog.get(cfg.DATASETS.TEST[0])

        checkpointer = DetectionCheckpointer(self.model)
        checkpointer.load(cfg.MODEL.WEIGHTS)

        self.input_format = cfg.INPUT.FORMAT
        assert self.input_format in ["RGB", "BGR"], self.input_format

    def __call__(self, original_image, model2):

        with torch.no_grad():  
            if self.input_format == "RGB":
                original_image = original_image[:, :, ::-1]
            height, width = original_image.shape[:2]
            image = torch.as_tensor(original_image.astype("float32").transpose(2, 0, 1))
            inputs = {"image": image, "height": height, "width": width}
            
            second_stream_outputs = inference_second_stream(model2, original_image)
            predictions = self.model([inputs], second_stream_outputs)[0]
            return predictions

def inference_second_stream(model, image):
    outputs = model(image)   
    return outputs 

def prepare_second_stream(weights=None, config_file=None, device="auto"):
    cfg2 = get_cfg()
    config_file = Path(config_file or PROJECT_ROOT / "src" / "configs" / "second_stream.yaml")
    if not config_file.is_file():
        raise FileNotFoundError("Second-stream config not found: {}".format(config_file))
    cfg2.merge_from_file(str(config_file))
    weights = weights or os.environ.get("CONTACTHANDS_SECOND_STREAM_WEIGHTS")
    if weights:
        if not str(weights).startswith("detectron2://"):
            weight_path = Path(weights).expanduser()
            if not weight_path.is_file():
                raise FileNotFoundError("Second-stream checkpoint not found: {}".format(weight_path))
            weights = str(weight_path.resolve())
    else:
        # Some project-local Detectron2 checkpointers do not resolve detectron2:// URIs.
        # Use the standard cache directly when present; keep the URI fallback portable.
        weights = (str(DEFAULT_SECOND_STREAM_CACHE)
                   if DEFAULT_SECOND_STREAM_CACHE.is_file()
                   else DEFAULT_SECOND_STREAM_URI)
    cfg2.MODEL.WEIGHTS = weights
    if device != "auto":
        cfg2.MODEL.DEVICE = device
    elif not torch.cuda.is_available():
        cfg2.MODEL.DEVICE = "cpu"
    model2 = CustomPredictor(cfg2)
    return model2

def prepare_first_stream(cfg_file, weights, roi_score_thresh, device="auto"):
    cfg1 = get_cfg()
    add_contacthands_config(cfg1)
    cfg_file = Path(cfg_file)
    weights = Path(weights).expanduser()
    if not cfg_file.is_file():
        raise FileNotFoundError("ContactHands config not found: {}".format(cfg_file))
    if not weights.is_file():
        raise FileNotFoundError("ContactHands checkpoint not found: {}".format(weights))
    cfg1.merge_from_file(str(cfg_file))
    cfg1.MODEL.ROI_HEADS.SCORE_THRESH_TEST = roi_score_thresh
    cfg1.MODEL.WEIGHTS = str(weights.resolve())
    if device != "auto":
        cfg1.MODEL.DEVICE = device
    elif not torch.cuda.is_available():
        cfg1.MODEL.DEVICE = "cpu"
    model1 = CustomPredictorTwoStream(cfg1)
    
    return model1   

def add_legend(im):
    cyan, magenta, red, yellow = (255, 255, 0), (255, 0, 255), (0, 0, 255),  (0, 255, 255)
    labels = ["No", "Self", "Person", "Object"]
    map_idx_to_color = {}
    map_idx_to_color[0], map_idx_to_color[1], map_idx_to_color[2],  map_idx_to_color[3] = \
    cyan, magenta, red, yellow

    font = cv2.FONT_HERSHEY_SIMPLEX
    h, w = im.shape[:2]
    image = 255*np.ones((h+50, w, 3), dtype=np.uint8)
    image[:h, :w, :] = im 
    h, w = image.shape[:2]
    offset = 0

    for itr, word in enumerate(labels):
        offset += int(w / len(labels)) - 50
        cv2.putText(image, word, (offset, h-15), font, 1, map_idx_to_color[itr], 3)

    return image

if __name__ == '__main__':

    parser = argparse.ArgumentParser(description='Arguments for evaluation')
    
    parser.add_argument('--image_dir', metavar='path to images', help='directory of images')
    parser.add_argument('--image', help='single image path')
    parser.add_argument('--weights', default=str(PROJECT_ROOT / 'models' / 'combined_data_model.pth'))
    parser.add_argument('--second-stream-weights', default=None)
    parser.add_argument('--output-dir', default=str(PROJECT_ROOT / 'results'))
    parser.add_argument('--device', choices=('auto', 'cpu', 'cuda'), default='auto')
    parser.add_argument('--ROI_SCORE_THRESH', type=float, metavar='hand threshold', default=0.7)
    parser.add_argument('--sc', type=float, help='self-contact threshold', default=0.5)
    parser.add_argument('--pc', type=float, help='other-person-contact threshold', default=0.4)
    parser.add_argument('--oc', type=float, help='object-contact threshold', default=0.6)

    args = parser.parse_args()
    if not args.image and not args.image_dir:
        parser.error('provide --image or --image_dir')
    for name in ('ROI_SCORE_THRESH', 'sc', 'pc', 'oc'):
        if not 0.0 <= getattr(args, name) <= 1.0:
            parser.error('--{} must be between 0 and 1'.format(name))
    roi_score_thresh = args.ROI_SCORE_THRESH
    sc_thresh, pc_thresh, oc_thresh = args.sc, args.pc, args.oc
    contact_thresh = [0.5, sc_thresh, pc_thresh, oc_thresh] 
    # if the scores for all contact states is less than corresponding thresholds, No-Contact is predicted; 0.5 is dummy here, it is not used.

    model2 = prepare_second_stream(args.second_stream_weights, device=args.device)
    model1 = prepare_first_stream(PROJECT_ROOT / 'src' / 'configs' / 'ContactHands.yaml',
                                  args.weights, roi_score_thresh, args.device)

    image_extensions = {'.jpg', '.jpeg', '.png', '.bmp', '.tif', '.tiff'}
    if args.image:
        images = [Path(args.image).expanduser()]
    else:
        images_path = Path(args.image_dir).expanduser()
        if not images_path.is_dir():
            parser.error('image directory does not exist: {}'.format(images_path))
        images = sorted(path for path in images_path.iterdir()
                        if path.is_file() and path.suffix.lower() in image_extensions)
        if not images:
            parser.error('image directory contains no supported images')
    output_dir = Path(args.output_dir).expanduser()
    output_dir.mkdir(parents=True, exist_ok=True)
    count = 0
    for img in images:
        count += 1
        im = cv2.imread(str(img))
        if im is None:
            print('SKIP unreadable image: {}'.format(img))
            continue
        height, width = im.shape[0], im.shape[1]
        ratio = height / width
        im = cv2.resize(im, (720, int(720*ratio)))
        outputs = model1(im, model2)
        v = CustomVisualizer(im[:, :, ::-1], MetadataCatalog.get("ContactHands_test"), scale=1, scores_thresh=contact_thresh)   
        v = v.draw_instance_predictions(outputs["instances"].to("cpu"))
        out_im = add_legend(v.get_image()[:, :, ::-1])
        output_path = output_dir / ('res_' + img.name)
        if not cv2.imwrite(str(output_path), out_im):
            raise OSError('could not write inference result: {}'.format(output_path))
        print('{}/{} {}'.format(count, len(images), output_path))


def overlap_ratio(hand_box, roi):
    x1 = max(hand_box[0], roi[0])
    y1 = max(hand_box[1], roi[1])
    x2 = min(hand_box[2], roi[2])
    y2 = min(hand_box[3], roi[3])

    if x2 <= x1 or y2 <= y1:
        return 0.0

    intersection = (x2 - x1) * (y2 - y1)
    hand_area = max(
        1.0,
        (hand_box[2] - hand_box[0]) *
        (hand_box[3] - hand_box[1])
    )

    return intersection / hand_area


def find_painting_touches(
    instances,
    roi,
    oc_thresh=0.6,
    overlap_thresh=0.3,
):
    if len(instances) == 0:
        return []

    instances = instances.to("cpu")
    boxes = instances.pred_boxes.tensor.detach().cpu().numpy()
    det_scores = instances.scores.detach().cpu().numpy()
    cats = instances.pred_cats.detach().cpu().numpy()

    oc_scores = cats[:, 3]

    alerts = []

    for box, oc in zip(boxes, oc_scores):
        if oc < oc_thresh:
            continue

        ratio = overlap_ratio(box, roi)

        if ratio >= overlap_thresh:
            alerts.append(
                (box, float(oc), float(ratio))
            )

    return alerts
