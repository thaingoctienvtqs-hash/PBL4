"""Scenario ground truth is controlled oracle metadata, never real video labels."""
import copy
from ..phase_e.controlled_cases import case,exported,control,stability,settings,controlled_cases
from ..scenarios import frame,detection
from ..phase_c.audit_scenarios import cases as old_cases

def build(name,values,expected=1,truth=None):
    rows=[]
    for i,(time,x,score,actor) in enumerate(values):
        rows.append(exported(frame(name+str(i),time,[] if x is None else [detection(x,score,actor)])))
    result=case(name,rows,expected)
    result["truth_events"]=truth if truth is not None else ([{"actor":"A","start":.4,"end":max(r["timestamp"] for r in rows)}] if expected else [])
    return result

def prefix(score=.6):
    return [(0,.25,score,"A"),(.2,.3,score,"A"),(.4,.45,score,"A")]

def cases_f():
    result=[]
    for kind in ("missing","frame_error"):
        old=copy.deepcopy(next(c for c in controlled_cases() if c["name"]=="explicit_"+("missing_frame" if kind=="missing" else "frame_error")))
        for r in old["records"]:
            if r["kind"]=="prediction":r["oracle"]["actors"]=["A"]*len(r["prediction"]["scores"])
        old["truth_events"]=[{"actor":"A","start":.4,"end":1.3}]
        result.append(old)
    result.append(build("multiple_missing",prefix()+[(.6,None,.6,None),(.8,None,.6,None),(1,None,.6,None)]+
                        [(t,.45,.6,"A") for t in (1.2,1.4,1.6)]))
    result.append(build("speed_direction_change",prefix()+[(.6,None,.6,None),(.8,.46,.6,"A"),(1,.455,.6,"A"),(1.2,.45,.6,"A")]))
    result.append(build("unsupported_large_motion",prefix()+[(.6,None,.6,None)]+[(t,.6,.6,"A") for t in (.8,1,1.2)],
                        0,[{"actor":"A","start":.4,"end":1.3}]))
    result.append(build("replacement_near_prediction",prefix(.1)+[(.6,None,.1,None)]+[(t,.575,.99,"B") for t in (.8,1,1.2)],0))
    result.append(build("replacement_indistinguishable",prefix(.1)+[(.6,None,.1,None)]+[(t,.45,.99,"B") for t in (.8,1,1.2)],0))
    c=build("replacement_scale_change",prefix(.1)+[(.6,None,.1,None)]+[(t,.45,.99,"B") for t in (.8,1,1.2)],0)
    for r in c["records"][4:]:r["prediction"]["pred_boxes"]=[[350,300,550,500]]
    result.append(c)
    result.append(build("recovered_low_contact_score",prefix()+[(.6,None,.6,None)]+[(t,.45,.149,"A") for t in (.8,1,1.2)],0))
    result.append(build("recover_current_score_invalid",prefix()+[(.6,None,.6,None),(.8,.45,.99,"A"),(1,.45,.99,"A"),(1.2,.45,.1,"A")],0))
    c=build("timeout_expired",prefix()+[(.6,None,.6,None)]+[(t,.45,.6,"A") for t in (2.6,2.8,3)],0,
            [{"actor":"A","start":.4,"end":3}]);result.append(c)
    c=build("camera_shake",prefix()+[(.6,None,.6,None)]+[(t,.45,.99,"A") for t in (.8,1,1.2,1.4,1.6)],0)
    c["truth_events"]=[{"actor":"A","start":.4,"end":1.6}]
    c["records"][4]["stability"]["status"]="MOVING";result.append(c)
    c=copy.deepcopy(c);c["name"]="camera_unknown"
    c["records"][4]["stability"]["status"]="UNKNOWN";result.append(c)
    result.append(build("printed_static",[(i*.2,.5,.99,"print") for i in range(15)],0))
    c=build("duplicate_and_bad_timestamp",prefix()+[(.6,None,.6,None)]+[(t,.45,.6,"A") for t in (.8,1,1.2)])
    duplicate=copy.deepcopy(c["records"][4]);duplicate["timestamp"]=.9;duplicate["received_timestamp"]=.9;duplicate["stability"]=stability(duplicate)
    c["records"].insert(5,duplicate)
    backwards=exported(frame("old",.7,[detection(.45,.6,"A")]));c["records"].insert(6,backwards)
    result.append(c)
    rows=old_cases()["hands_cross_offset_0.0"]
    for index in (7,8,9):rows[index]["detections"]=[]
    c=case("crossing_after_missing",[exported(r) for r in rows],0)
    c["truth_events"]=[{"actor":"A","start":1.2,"end":3.2}];result.append(c)
    c=build("two_candidates_after_gap",prefix(.1)+[(.6,None,.1,None)]+[(t,.45,.99,"B") for t in (.8,1,1.2)],0)
    for r in c["records"][4:]:
        r["prediction"]["pred_boxes"].append([420,300,520,500])
        r["prediction"]["scores"].append(.99);r["prediction"]["pred_cats"].append([.3,.4,.2,.99])
        r["oracle"]["actors"].append("C")
    result.append(c)
    return result
