"""Clearly labeled synthetic background geometry. Never allowed by production defaults."""
from .pipeline_d import PipelineD

REFERENCE="controlled_reference_not_image_verified"

def background(frame_id,timestamp,session="session0",dx=0.0,dy=0.0):
    values=(.02,.08,.14,.86,.92,.98)
    matches=[[x,y,x+dx,y+dy,0.0] for x in values for y in values]
    return {"provider":"controlled_fixture","reference_id":REFERENCE,"frame_id":str(frame_id),
            "timestamp":timestamp,"source_session":session,"matches":matches}

def pipeline(config=None):
    return PipelineD(config,calibration_id=REFERENCE,test_mode=True)

def feed(p,row,dx=0.0,dy=0.0):
    return p.step(**row,camera_context=background(row["frame_id"],row["timestamp"],p.source_session,dx,dy))

def evaluate_d(frames,timeout=2,background_mode="unknown"):
    p=pipeline({"tracking":{"max_idle_seconds":timeout}});rows=[]
    for frame in frames:
        if background_mode=="controlled_stable":
            rows.append(feed(p,frame))
        elif background_mode=="unknown":
            rows.append(p.step(**frame))
        else:
            raise ValueError("Camera context must be explicitly selected")
    return rows
