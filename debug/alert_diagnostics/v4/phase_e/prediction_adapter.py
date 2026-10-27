"""Strict bridge from serialized ContactHands Instances to normalized Phase D detections."""
import math

CONTACT_ORDER=("No-Contact","Self-Contact","Other-Person-Contact","Object-Contact")
MAX_DETECTIONS=32

def number(value,name):
    if isinstance(value,bool) or not isinstance(value,(int,float)):
        raise ValueError(name+" must be a JSON number")
    try:result=float(value)
    except (ValueError,OverflowError):raise ValueError(name+" must be finite")
    if not math.isfinite(result):raise ValueError(name+" must be finite")
    return result

def probability(value,name):
    result=number(value,name)
    if not 0<=result<=1:raise ValueError(name+" must be in [0,1]")
    return result

def convert_prediction(record):
    size=record.get("image_size")
    if not isinstance(size,list) or len(size)!=2 or any(isinstance(v,bool) or not isinstance(v,int) or v<=0 for v in size):
        raise ValueError("image_size must be [height,width] positive integers")
    height,width=size
    space=record.get("coordinate_space")
    if space not in ("pixels_xyxy","normalized_xyxy"):
        raise ValueError("Explicit coordinate_space required")
    prediction=record.get("prediction")
    if not isinstance(prediction,dict) or set(prediction)!={"pred_boxes","scores","pred_cats"}:
        raise ValueError("prediction must contain exactly pred_boxes/scores/pred_cats")
    boxes,scores,cats=[prediction[k] for k in ("pred_boxes","scores","pred_cats")]
    if any(not isinstance(a,list) for a in (boxes,scores,cats)):
        raise ValueError("Prediction fields must be JSON arrays")
    if len(boxes)!=len(scores) or len(boxes)!=len(cats) or len(boxes)>MAX_DETECTIONS:
        raise ValueError("Prediction array lengths mismatch or detection limit exceeded")
    detections=[];conversion=[]
    for index,(box,score,contacts) in enumerate(zip(boxes,scores,cats)):
        if not isinstance(box,list) or len(box)!=4:raise ValueError("bbox must have four XYXY coordinates")
        raw=[number(v,"bbox coordinate") for v in box]
        if raw[0]>=raw[2] or raw[1]>=raw[3]:raise ValueError("bbox is empty or inverted")
        if not isinstance(contacts,list) or len(contacts)!=4:raise ValueError("pred_cats must have four independent sigmoid scores")
        values=[probability(v,"contact score") for v in contacts]
        hand=probability(score,"hand score")
        normalized=raw if space=="normalized_xyxy" else [raw[0]/width,raw[1]/height,raw[2]/width,raw[3]/height]
        # D owns clipping and threshold filtering. Do not change its scores or gates.
        detections.append({"box":normalized,"hand_score":hand,"object_contact_score":values[3]})
        conversion.append({"input_index":index,"original_box":raw,"normalized_box":normalized,
                           "will_clip_in_phase_d":any(v<0 or v>1 for v in normalized),
                           "hand_score":hand,"contact_scores":dict(zip(CONTACT_ORDER,values))})
    return detections,conversion

def serialize_instances(instances):
    """Optional CPU-only duck-typed serializer; never constructs or invokes a model."""
    for name in ("pred_boxes","scores","pred_cats"):
        if not instances.has(name):raise ValueError("Instances missing "+name)
    for tensor in (instances.pred_boxes.tensor,instances.scores,instances.pred_cats):
        device=getattr(tensor,"device",None)
        if device is not None and getattr(device,"type",str(device))!="cpu":
            raise ValueError("Phase E refuses non-CPU Instances; explicit export must happen upstream")
    return {"pred_boxes":instances.pred_boxes.tensor.tolist(),
            "scores":instances.scores.tolist(),"pred_cats":instances.pred_cats.tolist()}
