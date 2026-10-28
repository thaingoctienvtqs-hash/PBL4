"""Opt-in SQL TEST non-destructive integration checks, no production connection."""
import json
import os
from pathlib import Path
import sys
import unittest
from uuid import uuid4
from datetime import datetime
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/"web/backend"))

class SQLTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from app.core.ai_ingest_config import load_config,build_test_engine
        path=os.environ.get("ARTGUARD_INTEGRATION_CONFIG")
        if not path: raise unittest.SkipTest("Explicit SQL TEST config required")
        cls.config=load_config(path)
        cls.engine=build_test_engine(cls.config)
    @classmethod
    def tearDownClass(cls):
        cls.engine.dispose()
    def test_01_identity_and_restricted_permissions(self):
        from sqlalchemy import text
        with self.engine.connect() as c:
            row=c.execute(text("SELECT DB_NAME(),USER_NAME(),ORIGINAL_LOGIN(),HAS_PERMS_BY_NAME(DB_NAME(),'DATABASE','CREATE TABLE'),IS_MEMBER('db_owner')")).one()
        self.assertEqual(row[0],"ArtGuard_Integration_TEST")
        self.assertEqual(row[1],"artguard_integration_app")
        self.assertEqual(row[3],0);self.assertEqual(row[4],0)
    def test_02_expected_schema_and_unique_index(self):
        from sqlalchemy import inspect
        with self.engine.connect() as c:
            ins=inspect(c)
            self.assertTrue({"ai_event_receipts","ai_event_attachments","alerts","evidences"}<=set(ins.get_table_names()))
            indexes=ins.get_indexes("ai_event_receipts")
            self.assertTrue(any(i["unique"] and set(i["column_names"])=={"producer_id","event_id"} for i in indexes))
    def test_03_explicit_transaction_rollback_leaves_no_receipt(self):
        from sqlalchemy import text
        ident=str(uuid4());p=self.config.producers[0]
        with self.engine.connect() as c:
            transaction=c.begin()
            try:
                c.execute(text("INSERT INTO ai_event_receipts(producer_id,event_id,producer_instance_id,source_event_id,schema_version,data_origin,event_type,detected_at,received_at,payload_sha256,payload_json) VALUES(:p,:e,:i,'ROLLBACK_TEST','1','SYNTHETIC_TEST','AI_CONTACT_SUSPECTED_IN_ROI',:t,:t,:h,'{}')"),
                          dict(p=p.producer_id,e=ident,i=p.producer_instance_id,t=datetime(2026,1,1),h="0"*64))
            finally:
                transaction.rollback()
            count=c.scalar(text("SELECT COUNT(*) FROM ai_event_receipts WHERE producer_id=:p AND event_id=:e"),dict(p=p.producer_id,e=ident))
        self.assertEqual(count,0)
    def test_04_new_pool_checkout_remains_restricted(self):
        from sqlalchemy import text
        for _ in range(3):
            with self.engine.connect() as c:
                self.assertEqual(c.scalar(text("SELECT USER_NAME()")),"artguard_integration_app")

if __name__=="__main__": unittest.main()
