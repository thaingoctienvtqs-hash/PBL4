"""SYNTHETIC_TEST core ingest tests: SQLite memory only, no network/model."""
from pathlib import Path
import hashlib
import importlib.util
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "full_integration"))
from test_support import IsolatedBackend

class CoreTests(unittest.TestCase):
    def setUp(self):
        self.fx = IsolatedBackend()
        from app.services import ai_event_ingest
        self.service = ai_event_ingest

    def tearDown(self):
        self.fx.close()

    def ingest(self, value=None):
        with self.fx.factory() as db:
            return self.service.ingest_event(db, value or self.fx.event(), self.fx.producer, self.fx.config)

    def test_atomic_ingest_rows_and_provenance(self):
        event = self.fx.event()
        ack, created = self.ingest(event)
        self.assertTrue(created)
        self.assertEqual(self.fx.counts(), (1, 1, 1, 1, 1, 1, 0, 0))
        self.assertEqual(ack.data_origin, "SYNTHETIC_TEST")
        with self.fx.factory() as db:
            alert = db.get(self.fx.models.Alert, ack.alert_id)
            evidence = db.get(self.fx.models.Evidence, ack.evidence_id)
            self.assertEqual(alert.source, "synthetic_test")
            self.assertEqual(evidence.source, "synthetic_test")
            self.assertIsNone(evidence.confidence)

    def test_exact_replay_no_duplicate(self):
        event = self.fx.event()
        first, _ = self.ingest(event)
        before = self.fx.counts()
        second, created = self.ingest(event)
        self.assertFalse(created)
        self.assertTrue(second.replayed)
        self.assertEqual(first.alert_id, second.alert_id)
        self.assertEqual(before, self.fx.counts())

    def test_payload_conflict_no_partial_write(self):
        event = self.fx.event()
        self.ingest(event)
        before = self.fx.counts()
        changed = event.model_copy(update={"source_event_id": "different"})
        from fastapi import HTTPException
        with self.assertRaises(HTTPException) as error:
            self.ingest(changed)
        self.assertEqual(error.exception.status_code, 409)
        self.assertEqual(before, self.fx.counts())

    def test_origin_scope_cannot_be_spoofed(self):
        from fastapi import HTTPException
        with self.assertRaises(HTTPException) as error:
            self.ingest(self.fx.event(data_origin="REAL_AI"))
        self.assertEqual(error.exception.status_code, 403)
        self.assertEqual(self.fx.counts(), (0,) * 8)

    def test_identity_scope_cannot_be_spoofed(self):
        from fastapi import HTTPException
        with self.assertRaises(HTTPException):
            self.ingest(self.fx.event(producer_id="other"))
        self.assertEqual(self.fx.counts(), (0,) * 8)

    def test_instance_scope_cannot_be_spoofed(self):
        from fastapi import HTTPException
        from uuid import uuid4
        with self.assertRaises(HTTPException):
            self.ingest(self.fx.event(producer_instance_id=str(uuid4())))
        self.assertEqual(self.fx.counts(), (0,) * 8)

    def test_mapping_scope_cannot_be_spoofed(self):
        from fastapi import HTTPException
        with self.assertRaises(HTTPException):
            self.ingest(self.fx.event(artwork_id=999))
        self.assertEqual(self.fx.counts(), (0,) * 8)

    def test_unrelated_integrity_error_rolls_back(self):
        from sqlalchemy.exc import IntegrityError
        failure = IntegrityError("synthetic", {}, Exception("unrelated foreign-key failure"))
        with patch.object(self.service, "record_audit", side_effect=failure):
            with self.assertRaises(IntegrityError):
                self.ingest()
        self.assertEqual(self.fx.counts(), (0,) * 8)

    def test_response_validation_failure_rolls_back(self):
        with patch.object(self.service, "acknowledgment", side_effect=RuntimeError("test precommit failure")):
            with self.assertRaises(RuntimeError):
                self.ingest()
        self.assertEqual(self.fx.counts(), (0,) * 8)

    def test_commit_failure_rolls_back(self):
        with self.fx.factory() as db:
            with patch.object(db, "commit", side_effect=RuntimeError("commit unavailable")):
                with self.assertRaises(RuntimeError):
                    self.service.ingest_event(db, self.fx.event(), self.fx.producer, self.fx.config)
        self.assertEqual(self.fx.counts(), (0,) * 8)

    def test_utc_equivalence_canonical(self):
        first = self.fx.event()
        second = first.model_copy(update={"detected_at": first.detected_at.astimezone(
            __import__("datetime").timezone(__import__("datetime").timedelta(hours=7)))})
        self.assertEqual(self.service.canonical_event(first), self.service.canonical_event(second))

    def test_nan_boolean_string_scores_rejected(self):
        from pydantic import ValidationError
        for score in (float("nan"), float("inf"), True, "0.9", -0.1, 1.1):
            with self.subTest(score=repr(score)), self.assertRaises(ValidationError):
                self.fx.event(scores={"object_contact": score})

    def test_naive_timestamp_rejected(self):
        from pydantic import ValidationError
        with self.assertRaises(ValidationError):
            self.fx.event(detected_at="2026-10-27T10:00:00")

    def test_unknown_field_and_path_rejected(self):
        from pydantic import ValidationError
        for change in ({"evidence_path": "../secret"}, {"evidence_ref": {"status": "PENDING", "path": "../x"}}):
            with self.subTest(change=change), self.assertRaises(ValidationError):
                self.fx.event(**change)

    def attach(self, ack, data):
        with self.fx.factory() as db:
            return self.service.attach_evidence(db, ack.event_id, self.fx.producer,
                self.fx.config, data, hashlib.sha256(data).hexdigest())

    def test_media_first_and_replay_origin(self):
        ack, _ = self.ingest()
        data = self.fx.jpeg()
        first, created = self.attach(ack, data)
        before = self.fx.counts()
        replay, created2 = self.attach(ack, data)
        self.assertTrue(created)
        self.assertFalse(created2)
        self.assertEqual(first.media_id, replay.media_id)
        self.assertEqual(first.data_origin, "SYNTHETIC_TEST")
        self.assertEqual(self.fx.counts(), before)

    def test_media_wrong_hash_no_write(self):
        from fastapi import HTTPException
        ack, _ = self.ingest()
        with self.fx.factory() as db:
            with self.assertRaises(HTTPException) as error:
                self.service.attach_evidence(db, ack.event_id, self.fx.producer, self.fx.config, self.fx.jpeg(), "a"*64)
        self.assertEqual(error.exception.status_code, 422)
        self.assertEqual(self.fx.counts()[-2:], (0, 0))

    def test_media_invalid_jpeg_no_write(self):
        from fastapi import HTTPException
        ack, _ = self.ingest()
        with self.assertRaises(HTTPException) as error:
            self.attach(ack, b"not a jpeg")
        self.assertEqual(error.exception.status_code, 415)
        self.assertEqual(self.fx.counts()[-2:], (0, 0))

    def test_media_different_payload_conflict(self):
        from fastapi import HTTPException
        ack, _ = self.ingest()
        self.attach(ack, self.fx.jpeg("white"))
        before = self.fx.counts()
        with self.assertRaises(HTTPException) as error:
            self.attach(ack, self.fx.jpeg("black"))
        self.assertEqual(error.exception.status_code, 409)
        self.assertEqual(before, self.fx.counts())

    def test_media_write_failure_rolls_back(self):
        ack, _ = self.ingest()
        original_open = Path.open
        def fail_on_write(path, mode="r", *args, **kwargs):
            if mode == "xb":
                raise OSError("synthetic disk failure")
            return original_open(path, mode, *args, **kwargs)
        with patch.object(Path, "open", fail_on_write):
            with self.assertRaises(OSError):
                self.attach(ack, self.fx.jpeg())
        self.assertEqual(self.fx.counts()[-2:], (0, 0))

    def test_old_receipt_reports_missing_without_overwriting(self):
        ack, _ = self.ingest()
        media_ack, _ = self.attach(ack, self.fx.jpeg())
        with self.fx.factory() as db:
            media = db.get(self.fx.models.EvidenceMedia, media_ack.media_id)
            media.file_path = "missing-artifact.jpg"
            db.commit()
            receipt = db.get(self.fx.ai_models.AiEventReceipt, ack.receipt_id)
            self.assertEqual(self.service.evidence_status(db, receipt, self.fx.config), "MISSING")

    def test_path_escape_stored_media_ref_rejected(self):
        from fastapi import HTTPException
        with self.assertRaises(HTTPException):
            self.service._safe_media_path(self.fx.config, "../escape.jpg")

    def test_migration_sqlite_additive_and_repeat(self):
        from alembic.migration import MigrationContext
        from alembic.operations import Operations
        file = Path(__file__).resolve().parents[2] / "web/backend/migrations/versions/0003_ai_event_receipts.py"
        spec = importlib.util.spec_from_file_location("migration_under_test", file)
        migration = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(migration)
        with self.fx.engine.begin() as connection:
            with Operations.context(MigrationContext.configure(connection)):
                migration.upgrade()
                migration.upgrade()
                migration.downgrade()
        self.assertEqual(self.fx.counts(), (0,) * 8)


    def load_migration(self):
        file = Path(__file__).resolve().parents[2] / "web/backend/migrations/versions/0003_ai_event_receipts.py"
        spec = importlib.util.spec_from_file_location("migration_key_test", file)
        value = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(value)
        return value

    def test_migration_mssql_catalog_fallback_without_reflection(self):
        from types import SimpleNamespace
        from unittest.mock import Mock
        migration = self.load_migration()
        bind = Mock()
        bind.dialect = SimpleNamespace(name="mssql")
        receipts = Mock()
        receipts.all.return_value = [("producer_id",), ("event_id",)]
        attachments = Mock()
        attachments.all.return_value = [("receipt_id",)]
        bind.exec_driver_sql.side_effect = [receipts, attachments]
        inspector = Mock()
        inspector.get_unique_constraints.side_effect = NotImplementedError
        inspector.get_pk_constraint.side_effect = NotImplementedError
        migration._verify_keys(bind, inspector)
        self.assertEqual(bind.exec_driver_sql.call_count, 2)
        inspector.get_unique_constraints.assert_not_called()
        inspector.get_pk_constraint.assert_not_called()
        for call in bind.exec_driver_sql.call_args_list:
            self.assertTrue(call.args[0].startswith("SELECT "))
            self.assertIn("sys.indexes", call.args[0])

    def test_migration_mssql_missing_unique_is_refused(self):
        from types import SimpleNamespace
        from unittest.mock import Mock
        migration = self.load_migration()
        bind = Mock()
        bind.dialect = SimpleNamespace(name="mssql")
        bind.exec_driver_sql.return_value.all.return_value = [("producer_id",)]
        with self.assertRaisesRegex(RuntimeError, "uniqueness"):
            migration._verify_keys(bind, Mock())
        self.assertEqual(bind.exec_driver_sql.call_count, 1)

    def test_migration_mssql_wrong_attachment_pk_is_refused(self):
        from types import SimpleNamespace
        from unittest.mock import Mock
        migration = self.load_migration()
        bind = Mock()
        bind.dialect = SimpleNamespace(name="mssql")
        good, bad = Mock(), Mock()
        good.all.return_value = [("producer_id",), ("event_id",)]
        bad.all.return_value = [("media_id",)]
        bind.exec_driver_sql.side_effect = [good, bad]
        with self.assertRaisesRegex(RuntimeError, "attachment"):
            migration._verify_keys(bind, Mock())

if __name__ == "__main__":
    unittest.main(verbosity=2)
