"""Synthetic software E2E using actual EventStore/outbox/HTTP, never camera."""
import argparse
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sys
import time
from uuid import uuid4
from urllib.request import Request, build_opener, ProxyHandler
from urllib.error import HTTPError

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from debug.full_integration.event_sender import (
    validate_config, ReadOnlyEventReader, SidecarOutbox, Sender, HttpTransport, NoRedirect, canonical)

def read(path):
    return json.loads(Path(path).read_text(encoding="utf8"))

def write_new(path, value):
    with Path(path).open("x", encoding="utf8") as handle:
        json.dump(value,handle,indent=2,default=str)

def request(path, data=None, token=None, producer=None):
    headers={"Content-Type":"application/json"}
    if token: headers["Authorization"]="Bearer "+token
    if producer: headers["X-ArtGuard-Producer-Key"]=producer
    body=None if data is None else canonical(data).encode("utf8")
    req=Request("http://127.0.0.1:8101"+path,data=body,headers=headers)
    begin=time.monotonic()
    try:
        with build_opener(ProxyHandler({}), NoRedirect()).open(req,timeout=15) as response:
            payload=response.read()
            return response.status,json.loads(payload) if payload else None,(time.monotonic()-begin)*1000
    except HTTPError as error:
        # Never print request headers or credential-bearing response bodies.
        return error.code,None,(time.monotonic()-begin)*1000

def prepare(run, source_case=None):
    run=Path(run).resolve()
    config=read(run/"integration_config.json")
    if config.get("profile")!="ARTGUARD_INTEGRATION_TEST" or config["database"]["name"]!="ArtGuard_Integration_TEST":
        raise RuntimeError("Approved TEST config required")
    private=read(run/"private_test_credentials.json")
    profile=private["synthetic"]
    mapping=next(p for p in config["producers"] if p["producer_id"]==profile["producer_id"])
    if not mapping.get("artwork_id") or not mapping.get("device_id"):
        raise RuntimeError("Approved TEST seed mapping required")
    case=run/("synthetic_"+datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")+"_"+uuid4().hex[:8])
    case.mkdir()
    from PIL import Image,ImageDraw
    image=Image.new("RGB",(320,240),(240,240,240))
    ImageDraw.Draw(image).text((20,100),"SYNTHETIC_TEST - NOT CAMERA",fill=(200,0,0))
    image.save(case/"synthetic_evidence.jpg","JPEG")
    from src.services.event_store import EventStore
    manifest_path=run/"synthetic_source.json"
    if manifest_path.exists():
        source_manifest=read(manifest_path)
        if not Path(source_manifest["source_db"]).is_file():
            raise RuntimeError("Manifest source is missing; refuse new database with reused identity")
    else:
        if source_case:
            previous=validate_config(read(Path(source_case)/"sender_config.json"))
            if previous["producer_id"]!=profile["producer_id"] or previous["producer_instance_id"]!=profile["producer_instance_id"]:
                raise RuntimeError("Source namespace differs from authorized synthetic producer")
            source_path=Path(previous["source_db"])
        else:
            if list(run.glob("synthetic_*/sender_config.json")):
                raise RuntimeError("Existing session sources: choose --source-case explicitly once")
            source_path=run/"synthetic_events.sqlite3"
            if source_path.exists():
                raise RuntimeError("Unverified existing source requires explicit adoption")
        source_manifest={"source_db":str(source_path),"producer_id":profile["producer_id"],
                         "producer_instance_id":profile["producer_instance_id"]}
        write_new(manifest_path,source_manifest)
    if source_manifest["producer_id"]!=profile["producer_id"] or source_manifest["producer_instance_id"]!=profile["producer_instance_id"]:
        raise RuntimeError("Source generation identity mismatch")
    source_path=Path(source_manifest["source_db"]).resolve()
    if run not in source_path.parents:
        raise RuntimeError("Synthetic source must remain inside external TEST run")
    store=EventStore(source_path)
    begin=time.monotonic()
    ident=store.record_event("AI_CONTACT_SUSPECTED_IN_ROI",{
        "alert_at":datetime.now(timezone.utc).isoformat(),"object_contact_score":.93,
        "data_origin":"SYNTHETIC_TEST","note":"Controlled software fixture, not AI inference"
    },evidence_path=case/"synthetic_evidence.jpg")
    commit=time.monotonic()
    cfg=dict(profile="TEST",test_root=str(run),source_db=str(source_path),
        outbox_db=str(case/"outbox.sqlite3"),evidence_root=str(case),backend_url="http://127.0.0.1:8101",
        producer_id=profile["producer_id"],producer_instance_id=profile["producer_instance_id"],
        data_origin="SYNTHETIC_TEST",artwork_id=mapping["artwork_id"],device_id=mapping["device_id"],
        source_start_id=ident-1,retry_base_seconds=1.,retry_cap_seconds=5.,max_attempts=5)
    cfg=validate_config(cfg)
    before=hashlib.sha256(source_path.read_bytes()).hexdigest()
    outbox=SidecarOutbox(cfg,ReadOnlyEventReader(cfg["source_db"]))
    queued=outbox.enqueue()
    end=time.monotonic()
    assert queued==1
    write_new(case/"sender_config.json",cfg)
    write_new(case/"prepare.json",dict(data_origin="SYNTHETIC_TEST",source_event_id=ident,
        event_id=outbox.rows()[0]["event_id"],source_sha256=before,
        source_commit_wall_ms=(commit-begin)*1000,eventstore_commit_to_outbox_wall_ms=(end-commit)*1000))
    print(json.dumps({"case":str(case),"event_id":outbox.rows()[0]["event_id"],"queued":queued}))
    return case

def deliver(case):
    case=Path(case).resolve()
    cfg=validate_config(read(case/"sender_config.json"))
    private=read(Path(cfg["test_root"])/"private_test_credentials.json")
    outbox=SidecarOutbox(cfg,ReadOnlyEventReader(cfg["source_db"]))
    sender=Sender(cfg,outbox,HttpTransport(cfg["backend_url"],private["synthetic"]["token"]))
    source_before=hashlib.sha256(Path(cfg["source_db"]).read_bytes()).hexdigest()
    t=time.monotonic()
    sent=sender.send_due()
    event_end=time.monotonic()
    media=sender.send_media()
    end=time.monotonic()
    rows=outbox.rows()
    assert hashlib.sha256(Path(cfg["source_db"]).read_bytes()).hexdigest()==source_before
    stamp=datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    report=dict(data_origin="SYNTHETIC_TEST",delivered=sent,media=media,
        event_http_and_outbox_ack_wall_ms=(event_end-t)*1000,
        media_http_and_outbox_ack_wall_ms=(end-event_end)*1000,
        rows=[{key:r[key] for key in ["event_id","source_id","state","attempts","error_code",
                                    "receipt_id","alert_id","evidence_id","media_state"]} for r in rows])
    write_new(case/("delivery_"+stamp+".json"),report)
    print(json.dumps(report))

def verify(case):
    case=Path(case).resolve();cfg=validate_config(read(case/"sender_config.json"))
    source_before=hashlib.sha256(Path(cfg["source_db"]).read_bytes()).hexdigest()
    run=Path(cfg["test_root"]);private=read(run/"private_test_credentials.json")
    outbox=SidecarOutbox(cfg,ReadOnlyEventReader(cfg["source_db"]))
    row=outbox.rows()[0];payload=json.loads(row["payload"]);key=private["synthetic"]["token"]
    assert row["state"]=="DELIVERED" and row["media_state"]=="DELIVERED"
    checks={}
    status,ack,wall=request("/api/v1/ai/events",payload,producer=key)
    checks["exact_replay_200"]=status==200 and ack["replayed"] and ack["alert_id"]==row["alert_id"]
    with ThreadPoolExecutor(max_workers=4) as pool:
        answers=list(pool.map(lambda _:request("/api/v1/ai/events",payload,producer=key),range(4)))
    checks["concurrent_replay_same_ids"]=all(s==200 and a["receipt_id"]==row["receipt_id"] for s,a,_ in answers)
    bad=dict(payload);bad["scores"]={"object_contact":.11}
    checks["conflict_409"]=request("/api/v1/ai/events",bad,producer=key)[0]==409
    bad=dict(payload);bad["event_id"]=str(uuid4());bad["detected_at"]="not-a-date"
    checks["malformed_422"]=request("/api/v1/ai/events",bad,producer=key)[0]==422
    checks["missing_producer_401"]=request("/api/v1/ai/events",payload)[0]==401
    bad=dict(payload);bad["data_origin"]="REAL_AI"
    checks["synthetic_cannot_be_real_403"]=request("/api/v1/ai/events",bad,producer=key)[0]==403
    user=next(u for u in private["users"] if u["username"]=="integration_viewer")
    status,login,_=request("/api/v1/auth/login",{"username":user["username"],"password":user["password"]})
    assert status==200
    token=login["access_token"]
    status,origins,_=request("/api/v1/ai/alert-origins?alert_ids="+str(row["alert_id"]),token=token)
    checks["query_identity_origin"]=status==200 and len(origins["items"])==1 and origins["items"][0]["event_id"]==row["event_id"] and origins["items"][0]["data_origin"]=="SYNTHETIC_TEST"
    status,alerts,_=request("/api/v1/alerts?source=synthetic_test&page_size=100",token=token)
    checks["alert_query"]=status==200 and any(a["id"]==row["alert_id"] for a in alerts["items"])
    checks["anonymous_query_denied"]=request("/api/v1/alerts")[0]==401
    sys.path.insert(0,str(ROOT/"web/backend"))
    from app.core.ai_ingest_config import load_config,build_test_engine
    from sqlalchemy import text
    engine=build_test_engine(load_config(run/"integration_config.json"))
    t=time.monotonic()
    with engine.connect() as connection:
        identity=connection.execute(text("SELECT DB_NAME(),USER_NAME()")).one()
        persisted=connection.execute(text("SELECT event_id,data_origin,alert_id,evidence_id FROM ai_event_receipts WHERE producer_id=:p AND event_id=:e"),
            {"p":cfg["producer_id"],"e":row["event_id"]}).mappings().all()
    query_wall=(time.monotonic()-t)*1000
    engine.dispose()
    checks["sql_test_restricted_identity"]=identity[0]=="ArtGuard_Integration_TEST" and identity[1]=="artguard_integration_app"
    checks["one_persisted_receipt"]=len(persisted)==1 and persisted[0]["data_origin"]=="SYNTHETIC_TEST" and persisted[0]["alert_id"]==row["alert_id"]
    checks["source_unchanged"]=hashlib.sha256(Path(cfg["source_db"]).read_bytes()).hexdigest()==source_before
    report={"checks":checks,"pass":all(checks.values()),"event_id":row["event_id"],"alert_id":row["alert_id"],
            "receipt_id":row["receipt_id"],"data_origin":"SYNTHETIC_TEST","replay_http_wall_ms":wall,
            "sql_read_verify_wall_ms":query_wall,"browser_e2e":"NOT_YET_TESTED","physical_touch_latency":"NOT_AVAILABLE"}
    stamp=datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    write_new(case/("verification_"+stamp+".json"),report)
    print(json.dumps(report))
    if not report["pass"]: raise RuntimeError("Software E2E gate failed")

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("action",choices=["prepare","deliver","verify"])
    p.add_argument("--run-root");p.add_argument("--case");p.add_argument("--source-case")
    args=p.parse_args()
    if args.action=="prepare": prepare(args.run_root,args.source_case)
    elif args.action=="deliver": deliver(args.case)
    else: verify(args.case)

if __name__=="__main__": main()
