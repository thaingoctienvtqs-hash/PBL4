"""Evaluate human-labeled windows/events from CSV. Never reads images or runs a model."""
import argparse
import csv
import hashlib
import json
from collections import defaultdict
from datetime import datetime,timezone
from pathlib import Path
import uuid
from .metrics import validate_manifest,make_windows,classification_report,event_report,number

def read_csv(path):
    with Path(path).open(encoding="utf-8-sig",newline="") as handle:
        return list(csv.DictReader(handle))

def union_length(intervals):
    end=None;total=0.0
    for a,b in sorted(intervals):
        if end is None or a>end:
            total+=b-a;end=b
        elif b>end:
            total+=b-end;end=b
    return total

def evaluate(manifest,intervals,events,predictions,alerts,protocol,split):
    validate_manifest(manifest)
    selected=[r for r in manifest if r["split"]==split]
    if not selected:raise ValueError("No approved real videos in requested split")
    if any(r.get("labels_approved")!="yes" for r in selected):
        raise ValueError("Human labels must be explicitly approved")
    by_video={r["video_id"]:r for r in selected}
    all_ids={r["video_id"] for r in manifest}
    for rows in (intervals,events,predictions,alerts):
        if any(r["video_id"] not in all_ids for r in rows):raise ValueError("Unknown video_id")
    annotations=defaultdict(list)
    for row in intervals:
        if row["video_id"] in by_video:annotations[row["video_id"]].append(row)
    windows=[];known_seconds=0.0;uncertain_seconds=0.0;negative_seconds=0.0
    for video,metadata in by_video.items():
        windows.extend(make_windows(video,metadata["duration_seconds"],annotations[video],protocol["window_seconds"]))
        for row in annotations[video]:
            duration=number(row["end_seconds"])-number(row["start_seconds"])
            if row["label"]=="uncertain":uncertain_seconds+=duration
            else:
                known_seconds+=duration
                if row["label"]=="no_contact":negative_seconds+=duration
    labels_by_video=annotations
    truth=[]
    for row in events:
        if row["video_id"] not in by_video:continue
        start,end=number(row["start_seconds"]),number(row["end_seconds"])
        if start<0 or end<=start or end>number(by_video[row["video_id"]]["duration_seconds"]):
            raise ValueError("Contact event outside clip")
        covered=union_length([(max(start,number(a["start_seconds"])),min(end,number(a["end_seconds"])))
                              for a in labels_by_video[row["video_id"]]
                              if a["label"]=="contact" and min(end,number(a["end_seconds"]))>max(start,number(a["start_seconds"]))])
        if abs(covered-(end-start))>1e-8:raise ValueError("Contact event not covered by contact labels")
        truth.append(dict(row,start_seconds=start,end_seconds=end))
    for video,rows in annotations.items():
        for row in rows:
            if row["label"]!="contact":continue
            start,end=number(row["start_seconds"]),number(row["end_seconds"])
            covered=union_length([(max(start,r["start_seconds"]),min(end,r["end_seconds"])) for r in truth
                                  if r["video_id"]==video and min(end,r["end_seconds"])>max(start,r["start_seconds"])])
            if abs(covered-(end-start))>1e-8:raise ValueError("Contact labels lack event annotations")
    predicted=[]
    for row in predictions:
        if row["video_id"] not in by_video:continue
        availability=int(row["available"])
        predicted.append(dict(row,window_index=int(row["window_index"]),available=availability,
                              predicted_contact=None if not row["predicted_contact"] else int(row["predicted_contact"])))
    classified=classification_report(windows,predicted)
    eligible_alerts=[];uncertain_alerts=0
    for row in alerts:
        if row["video_id"] not in by_video:continue
        when=number(row["trigger_source_seconds"])
        if not 0<=when<number(by_video[row["video_id"]]["duration_seconds"]):raise ValueError("Alert outside clip")
        human=next(a["label"] for a in annotations[row["video_id"]]
                   if number(a["start_seconds"])<=when<number(a["end_seconds"]))
        if human=="uncertain":
            uncertain_alerts+=1;continue
        eligible_alerts.append(dict(row,trigger_source_seconds=when,
                                   emitted_elapsed_seconds=None if not row.get("emitted_elapsed_seconds") else number(row["emitted_elapsed_seconds"])))
    event_metrics=event_report(truth,eligible_alerts,known_seconds,
                              protocol["early_tolerance_seconds"],protocol["late_tolerance_seconds"],
                              protocol["max_detection_delay_seconds"])
    fraction=uncertain_seconds/(known_seconds+uncertain_seconds)
    target_counts=[w["target"] for w in windows if w["target"] is not None]
    readiness=[]
    if classified["metrics"] is None:readiness.append("incomplete_predictions")
    if not all(v in target_counts for v in (0,1)):readiness.append("both_classes_required")
    if fraction>protocol["max_uncertain_exposure_fraction"]:readiness.append("too_much_uncertain_exposure")
    return {"classification":classified,"events":event_metrics,"uncertain_seconds":uncertain_seconds,
            "negative_seconds":negative_seconds,"uncertain_alerts_excluded":uncertain_alerts,
            "uncertain_exposure_fraction":fraction,"split":split,"video_count":len(selected),
            "session_count":len({r["session_id"] for r in selected}),
            "target_assessment_status":"READY_TO_REVIEW" if not readiness else "BLOCKED",
            "target_assessment_blockers":readiness,
            "note":"No automatic >=80% claim; sample size, independence and confidence intervals require review"}

def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    for name in ("manifest","intervals","events","predictions","alerts"):
        parser.add_argument("--"+name,required=True)
    parser.add_argument("--split",choices=("validation","test"),required=True)
    parser.add_argument("--protocol",default=str(Path(__file__).with_name("protocol.json")))
    args=parser.parse_args(argv)
    paths={name:Path(getattr(args,name)).resolve() for name in ("manifest","intervals","events","predictions","alerts","protocol")}
    protocol=json.loads(paths["protocol"].read_text())
    report=evaluate(*(read_csv(paths[name]) for name in ("manifest","intervals","events","predictions","alerts")),
                    protocol,args.split)
    here=Path(__file__).resolve().parent
    directory=here/"evaluations"
    if directory.is_symlink():raise ValueError("Unsafe output directory")
    directory.mkdir(exist_ok=True)
    run=directory/(datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")+"_"+uuid.uuid4().hex[:8])
    run.mkdir(exist_ok=False)
    report["input_sha256"]={name:hashlib.sha256(path.read_bytes()).hexdigest() for name,path in paths.items()}
    report["protocol"]=protocol
    with (run/"metrics.json").open("x") as handle:json.dump(report,handle,indent=2,allow_nan=False)
    print("ARTIFACTS="+str(run))
    return 0

if __name__=="__main__":
    raise SystemExit(main())
