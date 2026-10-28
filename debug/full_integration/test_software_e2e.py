"""Actual SQLite/PIL synthetic prepare regression; no network, SQL Server, camera/model."""
import contextlib
import hashlib
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from debug.full_integration import software_e2e as e2e
from debug.full_integration.event_sender import ReadOnlyEventReader, SidecarOutbox, validate_config
from src.services.event_store import EventStore

INSTANCE="7b2f23c8-8b3e-4ff5-8d30-132e363f4f64"
def save(path,data):
    with Path(path).open("x",encoding="utf8") as handle:json.dump(data,handle)
def digest(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()
class FakeTransport:
    calls=[]
    def __init__(self,*args):self.event=None
    def request(self,path,data,content_type,headers=None):
        if content_type=="application/json":
            self.event=json.loads(data)
            ident=int(self.event["source_event_id"])
            ack=dict(schema_version="1",event_id=self.event["event_id"],producer_id=self.event["producer_id"],
                     receipt_id=ident,alert_id=ident,evidence_id=ident,data_origin="SYNTHETIC_TEST",
                     replayed=False,evidence_status="PENDING")
        else:
            ident=int(self.event["source_event_id"])
            ack=dict(schema_version="1",event_id=self.event["event_id"],producer_id=self.event["producer_id"],
                     receipt_id=ident,alert_id=ident,evidence_id=ident,data_origin="SYNTHETIC_TEST",
                     replayed=False,evidence_status="READY",media_id=ident)
        type(self).calls.append((path,content_type))
        return 201,ack

class SyntheticPrepareTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)
        self.run=self.make_run(self.root/"run")
    def make_run(self,root):
        root.mkdir()
        save(root/"integration_config.json",{"profile":"ARTGUARD_INTEGRATION_TEST",
             "database":{"name":"ArtGuard_Integration_TEST"},"producers":[{"producer_id":"synthetic-producer","artwork_id":1,"device_id":1}]})
        save(root/"private_test_credentials.json",{"synthetic":{"producer_id":"synthetic-producer","producer_instance_id":INSTANCE,
             "data_origin":"SYNTHETIC_TEST","token":"SYNTHETIC_TEST_ONLY_NOT_SECRET"}})
        return root
    def prepare(self,run=None,source_case=None):
        with contextlib.redirect_stdout(io.StringIO()):
            return e2e.prepare(run or self.run,source_case=source_case)
    def test_two_prepares_keep_source_and_distinct_event_ids_without_rewriting_first(self):
        first=self.prepare();cfg1=e2e.read(first/"sender_config.json")
        before_row=ReadOnlyEventReader(cfg1["source_db"]).get(1)
        old_artifacts={p.name:digest(p) for p in first.iterdir() if p.is_file()}
        second=self.prepare();cfg2=e2e.read(second/"sender_config.json")
        p1=e2e.read(first/"prepare.json");p2=e2e.read(second/"prepare.json")
        self.assertEqual(cfg1["source_db"],cfg2["source_db"])
        self.assertEqual((p1["source_event_id"],p2["source_event_id"]),(1,2))
        self.assertNotEqual(p1["event_id"],p2["event_id"])
        self.assertEqual(cfg2["source_start_id"],1)
        self.assertEqual(before_row,ReadOnlyEventReader(cfg1["source_db"]).get(1))
        self.assertEqual(old_artifacts,{p.name:digest(p) for p in first.iterdir() if p.is_file()})
        for case,cfg in [(first,cfg1),(second,cfg2)]:
            rows=SidecarOutbox(validate_config(cfg),ReadOnlyEventReader(cfg["source_db"])).rows()
            self.assertEqual(len(rows),1)
            self.assertEqual(json.loads(rows[0]["payload"])["data_origin"],"SYNTHETIC_TEST")
    def test_old_case_delivery_after_append_is_readonly_and_does_not_resend_ack(self):
        first=self.prepare();second=self.prepare()
        cfg=e2e.read(first/"sender_config.json");source=Path(cfg["source_db"])
        before=digest(source);FakeTransport.calls=[]
        with patch.object(e2e,"HttpTransport",FakeTransport),contextlib.redirect_stdout(io.StringIO()):
            e2e.deliver(first)
            e2e.deliver(first)
            e2e.deliver(second)
        self.assertEqual(before,digest(source))
        self.assertEqual(len(FakeTransport.calls),4)
        for case in [first,second]:
            cfg=e2e.read(case/"sender_config.json")
            rows=SidecarOutbox(validate_config(cfg),ReadOnlyEventReader(cfg["source_db"])).rows()
            self.assertEqual(rows[0]["state"],"DELIVERED")
            self.assertEqual(rows[0]["media_state"],"DELIVERED")
            reports=list(case.glob("delivery_*.json"))
            self.assertTrue(reports)
    def test_source_case_adoption_appends_without_changing_previous_row(self):
        previous=self.run/"synthetic_previous";previous.mkdir()
        source=previous/"events.sqlite3"
        EventStore(source).record_event("AI_CONTACT_SUSPECTED_IN_ROI",{"alert_at":"2026-10-28T00:00:00Z","data_origin":"SYNTHETIC_TEST"})
        cfg=dict(profile="TEST",test_root=str(self.run),source_db=str(source),outbox_db=str(previous/"outbox.sqlite3"),
                 evidence_root=str(previous),backend_url="http://127.0.0.1:8101",producer_id="synthetic-producer",
                 producer_instance_id=INSTANCE,data_origin="SYNTHETIC_TEST")
        save(previous/"sender_config.json",cfg)
        before=ReadOnlyEventReader(source).get(1)
        case=self.prepare(source_case=previous)
        self.assertEqual(e2e.read(case/"prepare.json")["source_event_id"],2)
        self.assertEqual(before,ReadOnlyEventReader(source).get(1))
        self.assertEqual(e2e.read(case/"sender_config.json")["source_db"],str(source))
    def test_external_source_case_refused_without_mutation(self):
        other=self.make_run(self.root/"other")
        foreign=self.prepare(other)
        cfg=e2e.read(foreign/"sender_config.json");before=digest(cfg["source_db"])
        with self.assertRaisesRegex(RuntimeError,"inside external TEST"):
            self.prepare(source_case=foreign)
        self.assertEqual(before,digest(cfg["source_db"]))
    def test_manifest_namespace_mismatch_refused_without_source_write(self):
        first=self.prepare();cfg=e2e.read(first/"sender_config.json");before=digest(cfg["source_db"])
        manifest=self.run/"synthetic_source.json"
        data=e2e.read(manifest);data["producer_instance_id"]="df39777e-024e-47a4-8eeb-4e8b1710ea74"
        manifest.write_text(json.dumps(data),encoding="utf8")
        with self.assertRaisesRegex(RuntimeError,"identity mismatch"):self.prepare()
        self.assertEqual(before,digest(cfg["source_db"]))

    def test_existing_unverified_default_source_refused_unchanged(self):
        source=self.run/"synthetic_events.sqlite3"
        source.write_bytes(b"unverified source sentinel")
        before=digest(source)
        with self.assertRaises(RuntimeError):self.prepare()
        self.assertEqual(before,digest(source))
        self.assertFalse((self.run/"synthetic_source.json").exists())
    def test_missing_manifest_source_refused_not_recreated(self):
        source=self.run/"missing.sqlite3"
        save(self.run/"synthetic_source.json",{"source_db":str(source),"producer_id":"synthetic-producer","producer_instance_id":INSTANCE})
        with self.assertRaisesRegex(RuntimeError,"source is missing"):self.prepare()
        self.assertFalse(source.exists())

if __name__=="__main__":unittest.main()
