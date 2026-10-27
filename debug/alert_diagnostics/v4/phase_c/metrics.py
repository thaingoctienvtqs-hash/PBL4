"""Independent arithmetic and annotation validation; no imports from v3/v4 logic."""
import math

EPS=1e-8

def number(value):
    if isinstance(value,bool):raise ValueError("Boolean is not a timestamp")
    value=float(value)
    if not math.isfinite(value):raise ValueError("Nonfinite number")
    return value

def divide(a,b):
    return a/b if b else None

def binary_metrics(tp,fp,fn,tn):
    for n in (tp,fp,fn,tn):
        if isinstance(n,bool) or not isinstance(n,int) or n<0:raise ValueError("Invalid count")
    return {"accuracy":divide(tp+tn,tp+fp+fn+tn),"precision":divide(tp,tp+fp),
            "recall":divide(tp,tp+fn),"f1":divide(2*tp,2*tp+fp+fn)}

def validate_manifest(rows):
    if not rows:raise ValueError("Empty real-video manifest")
    ids=set();sessions={};groups={};hashes={}
    for row in rows:
        video=row["video_id"];split=row["split"]
        if not video or video in ids:raise ValueError("Duplicate/empty video_id")
        ids.add(video)
        if split not in ("pilot","validation","test"):raise ValueError("Invalid split")
        if number(row["duration_seconds"])<=0:raise ValueError("Invalid duration")
        digest=row["sha256"].lower()
        if len(digest)!=64 or any(c not in "0123456789abcdef" for c in digest):raise ValueError("Invalid SHA256")
        if digest in hashes:raise ValueError("Duplicate video content, including within a split")
        for value,registry in ((row["session_id"],sessions),(row["capture_group_id"],groups),(digest,hashes)):
            if not value:raise ValueError("Missing session/group")
            if value in registry and registry[value]!=split:raise ValueError("Cross-split leakage")
            registry[value]=split
    return True

def make_windows(video_id,duration,intervals,window_seconds=1.0):
    duration=number(duration);window=number(window_seconds)
    if duration<=0 or window<=0:raise ValueError("Invalid video/window duration")
    rows=sorted(intervals,key=lambda r:number(r["start_seconds"]))
    end=0.0;validated=[]
    for row in rows:
        start,stop=number(row["start_seconds"]),number(row["end_seconds"])
        if abs(start-end)>EPS or stop<=start or stop>duration+EPS:raise ValueError("Annotation gap/overlap/bounds")
        label=row["label"]
        if label not in ("contact","no_contact","uncertain"):raise ValueError("Unknown human label")
        validated.append((start,stop,label));end=stop
    if abs(end-duration)>EPS:raise ValueError("Annotations must cover the whole clip")
    result=[];index=0
    while index*window<duration-EPS:
        start=index*window;stop=min(duration,(index+1)*window)
        touching=[label for a,b,label in validated if min(stop,b)-max(start,a)>EPS]
        target=None if "uncertain" in touching else int("contact" in touching)
        result.append({"video_id":video_id,"window_index":index,"start_seconds":start,
                       "end_seconds":stop,"target":target})
        index+=1
    return result

def classification_report(windows,predictions):
    expected={}
    for window in windows:
        key=(window["video_id"],window["window_index"])
        if key in expected:raise ValueError("Duplicate expected window")
        if window["target"] not in (0,1,None):raise ValueError("Invalid target")
        expected[key]=window
    predicted={}
    for row in predictions:
        key=(row["video_id"],row["window_index"])
        if key not in expected or key in predicted:raise ValueError("Unexpected/duplicate prediction window")
        available=row["available"]
        if available not in (0,1):raise ValueError("Invalid availability")
        if available and row["predicted_contact"] not in (0,1):raise ValueError("Invalid prediction")
        expected_row=expected[key]
        for field in ("start_seconds","end_seconds"):
            if abs(number(row[field])-number(expected_row[field]))>EPS:raise ValueError("Prediction/label grid mismatch")
        predicted[key]=row
    tp=fp=fn=tn=unknown=unavailable_pos=unavailable_neg=0
    for key,window in expected.items():
        target=window["target"]
        if target is None:
            unknown+=1;continue
        row=predicted.get(key)
        if row is None or not row["available"]:
            if target:unavailable_pos+=1
            else:unavailable_neg+=1
        else:
            positive=row["predicted_contact"]
            if target and positive:tp+=1
            elif target:fn+=1
            elif positive:fp+=1
            else:tn+=1
    known=tp+fp+fn+tn+unavailable_pos+unavailable_neg
    complete=known>0 and unavailable_pos+unavailable_neg==0
    return {"status":"COMPLETE" if complete else "BLOCKED_INCOMPLETE_OR_NO_KNOWN_LABELS",
            "confusion_matrix":{"rows":["actual_contact","actual_no_contact"],
                                "columns":["predicted_contact","predicted_no_contact","unavailable"],
                                "counts":[[tp,fn,unavailable_pos],[fp,tn,unavailable_neg]]},
            "coverage":divide(tp+fp+fn+tn,known),"unknown_windows":unknown,"known_windows":known,
            "metrics":binary_metrics(tp,fp,fn,tn) if complete else None,
            "available_only_diagnostic_metrics":binary_metrics(tp,fp,fn,tn),
            "unavailable_windows_are_not_true_negatives":True}

def percentile(values,q):
    if not values:return None
    values=sorted(values);position=(len(values)-1)*q
    lo=int(math.floor(position));hi=int(math.ceil(position))
    return values[lo]+(values[hi]-values[lo])*(position-lo)

def event_report(truth,alerts,known_seconds,early_tolerance=0.0,late_tolerance=.5,max_delay=2.0):
    known_seconds=number(known_seconds)
    if known_seconds<0:raise ValueError("Negative exposure")
    early,late,delay=[number(v) for v in (early_tolerance,late_tolerance,max_delay)]
    if early<0 or late<0 or delay<=0:raise ValueError("Invalid event tolerances")
    gt=sorted(truth,key=lambda r:(r["video_id"],number(r["start_seconds"]),str(r["event_id"])))
    pred=sorted(alerts,key=lambda r:(r["video_id"],number(r["trigger_source_seconds"]),str(r["event_id"])))
    for rows in (gt,pred):
        keys=[(r["video_id"],r["event_id"]) for r in rows]
        if len(keys)!=len(set(keys)):raise ValueError("Duplicate event identifier")
    for r in gt:
        if number(r["start_seconds"])<0 or number(r["end_seconds"])<=number(r["start_seconds"]):raise ValueError("Invalid contact interval")
    for r in pred:
        t=number(r["trigger_source_seconds"])
        if t<0:raise ValueError("Invalid alert time")
        if r.get("emitted_elapsed_seconds") is not None and number(r["emitted_elapsed_seconds"])<t:
            raise ValueError("Emit timestamp precedes source observation")
    neighbors={}
    for i,g in enumerate(gt):
        eligible=[]
        for j,p in enumerate(pred):
            if g["video_id"]!=p["video_id"]:continue
            if g.get("artwork_id") and p.get("artwork_id") and g["artwork_id"]!=p["artwork_id"]:continue
            when=number(p["trigger_source_seconds"]);start=number(g["start_seconds"]);end=number(g["end_seconds"])
            if start-early-EPS<=when<=min(end+late,start+delay)+EPS:
                eligible.append(j)
        neighbors[i]=sorted(eligible,key=lambda j:(abs(number(pred[j]["trigger_source_seconds"])-number(g["start_seconds"])),j))
    assigned={}
    def augment(i,visited):
        for j in neighbors[i]:
            if j in visited:continue
            visited.add(j)
            if j not in assigned or augment(assigned[j],visited):
                assigned[j]=i
                return True
        return False
    for i in range(len(gt)):augment(i,set())
    pairs=[];source_latency=[];emitted_latency=[]
    for j,i in sorted(assigned.items(),key=lambda item:item[1]):
        g,p=gt[i],pred[j]
        source=number(p["trigger_source_seconds"])-number(g["start_seconds"])
        emitted=None if p.get("emitted_elapsed_seconds") is None else number(p["emitted_elapsed_seconds"])-number(g["start_seconds"])
        source_latency.append(source)
        if emitted is not None:emitted_latency.append(emitted)
        pairs.append({"video_id":g["video_id"],"truth_event":g["event_id"],"alert_event":p["event_id"],
                      "source_confirmation_delay_seconds":source,"emission_delay_seconds":emitted})
    tp=len(pairs);fp=len(pred)-tp;fn=len(gt)-tp
    return {"tp":tp,"fp":fp,"fn":fn,"tn":None,"precision":divide(tp,tp+fp),"recall":divide(tp,tp+fn),
            "f1":divide(2*tp,2*tp+fp+fn),"matched_pairs":pairs,
            "false_alerts_per_known_monitoring_hour":divide(fp,known_seconds/3600.0),
            "known_monitoring_seconds":known_seconds,
            "latency_detected_events_only":{"source_p50":percentile(source_latency,.5),
                                           "source_p95":percentile(source_latency,.95),
                                           "emission_p50":percentile(emitted_latency,.5),
                                           "emission_p95":percentile(emitted_latency,.95),
                                           "source_count":len(source_latency),"emission_count":len(emitted_latency)},
            "matching":"deterministic maximum-cardinality one-to-one; not globally minimum latency",
            "offline_source_delay_is_not_live_camera_latency":True}


def trace_to_windows(windows,trace):
    """Fixed source-time bins, no look-ahead or forward-filling stale alerts.

    model_frame_available must be explicitly True only after fresh successful inference.
    This function never reads human targets to determine the predicted class.
    """
    output={(w["video_id"],w["window_index"]):dict(w,predicted_contact=None,available=0,fresh_frame_count=0)
            for w in windows}
    by_video={}
    for key,row in output.items():by_video.setdefault(key[0],[]).append(row)
    previous={};ids=set()
    for row in trace:
        video=row["video_id"]
        if video not in by_video:raise ValueError("Unknown trace video")
        if row.get("accepted") is not True or row.get("model_frame_available") is not True:continue
        when=number(row["timestamp"])
        identifier=(video,str(row["frame_id"]))
        if identifier in ids or (video in previous and when<=previous[video]):
            raise ValueError("Duplicate/non-monotonic successful model frames")
        candidates=[w for w in by_video[video] if w["start_seconds"]<=when<w["end_seconds"]]
        if len(candidates)!=1:raise ValueError("Trace timestamp outside fixed windows")
        window=candidates[0]
        positive=int(any(t.get("state")=="ALERT" for t in row.get("tracks",[])))
        window["available"]=1
        window["predicted_contact"]=max(window["predicted_contact"] or 0,positive)
        window["fresh_frame_count"]+=1
        previous[video]=when;ids.add(identifier)
    return [output[(w["video_id"],w["window_index"])] for w in windows]
