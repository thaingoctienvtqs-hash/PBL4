"""Controlled normalized predictions, not images, datasets, or model output."""
def detection(x, score=.6, label=None):
    return {"box":[x-.05,.3,x+.05,.5],"hand_score":.99,
            "object_contact_score":score,"label":label}

def frame(index, timestamp, detections):
    return {"frame_id":str(index),"timestamp":timestamp,"detections":detections}

def single(values):
    return [frame(i,t,[] if x is None else [detection(x,score)])
            for i,(t,x,score) in enumerate(values)]

def scenarios():
    return {
        "initial_inside":single([(i*.2,.5,.6) for i in range(6)]),
        "normal_entry_hold":single([(0,.25,.6),(.2,.3,.6)]+[(i*.2,.45,.6) for i in range(2,18)]),
        "slow_entry":single([(i*.2,x/1000.0,.6) for i,x in enumerate(range(350,491,10))]),
        "short_detection_loss":single([(0,.25,.6),(.2,.3,.6),(.4,.45,.6),(.6,.45,.6),
                                        (.8,None,.6),(1,.45,.6),(1.2,.45,.6),(1.4,.45,.6)]),
        "long_detection_loss":single([(0,.25,.6),(.2,.3,.6),(.4,.45,.6),(.6,None,.6),(4,.45,.6)]),
        "gap_1_01":single([(0,.25,.6)]+[(i*1.01,.45,.6) for i in range(1,6)]),
        "uneven_frames":single([(0,.25,.6),(.2,.3,.6),(1.31,.45,.6),(2.42,.45,.6),
                                (3.8,.45,.6),(4.1,.45,.6)]),
        "depicted_static":single([(i*.2,.5,.99) for i in range(20)]),
        "pass_by_low_score":single([(0,.25,.1),(.2,.3,.1),(.4,.45,.1),(.6,.6,.1),(.8,.85,.1)]),
        "pass_by_one_spike":single([(0,.25,.6),(.2,.3,.6),(.4,.45,.6),(.6,.85,.1)]),
        "score_oscillation":single([(0,.25,.6),(.2,.3,.6)]+
                                   [((i+2)*.2,.45,score) for i,score in enumerate([.151,.149]*4)]),
        "fast_path":single([(0,.25,.85),(.2,.3,.85),(.4,.45,.85),(.6,.45,.85)]),
        "multiple_hands":[frame(i,i*.2,([detection(x,.6,"left"),detection(y,.6,"right")]
                                       if i%2==0 else [detection(y,.6,"right"),detection(x,.6,"left")]))
                          for i,(x,y) in enumerate([(.15,.9),(.3,.85),(.45,.85),(.45,.85),
                                                     (.45,.85),(.45,.85)])],
    }
