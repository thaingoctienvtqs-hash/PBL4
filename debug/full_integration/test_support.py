"""SQLite-only isolated backend fixture. All media are SYNTHETIC_TEST artifacts."""
from pathlib import Path
import hashlib
import io
import os
import socket
import sys
import tempfile
from unittest.mock import patch
from uuid import uuid4

PROJECT = Path(__file__).resolve().parents[2]
BACKEND = PROJECT / "web" / "backend"
DEPS = Path(r"C:\Users\LEGION\pbl4_test_deps_stepA_20261022T112244884173Z_9118a5b5")
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))
if DEPS.is_dir() and str(DEPS) not in sys.path:
    sys.path.append(str(DEPS))
_PASSWORD_HASH = None

def remove_app_modules():
    for name in sorted(list(sys.modules), reverse=True):
        if name == "app" or name.startswith("app."):
            sys.modules.pop(name, None)

class IsolatedBackend:
    def __init__(self, http=False):
        assert sys.dont_write_bytecode, "Run isolated tests with -B"
        assert not any(n == "app.db" or n == "app.main" for n in sys.modules), "Use a dedicated process"
        from sqlalchemy import create_engine, event
        from sqlalchemy.pool import StaticPool
        from app.core.ai_ingest_config import IntegrationConfig, Producer, PROFILE
        from app.integration_app import create_app
        from fastapi.testclient import TestClient
        parent = os.environ.get("ARTGUARD_TEST_ARTIFACTS")
        self.root = Path(tempfile.mkdtemp(prefix="SYNTHETIC_TEST_ingest_", dir=parent))
        self.token = "synthetic-unit-test-producer-token"
        self.instance = str(uuid4())
        self.config = IntegrationConfig(
            PROFILE, {"kind": "sqlite", "name": ":memory:"},
            self.root / "media", self.root / "artworks", "SYNTHETIC_TEST_JWT_KEY_" + "x" * 40,
            (Producer("unit-producer", hashlib.sha256(self.token.encode()).hexdigest(),
                      ("SYNTHETIC_TEST",), self.instance, 1, 1),))
        self.engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
        @event.listens_for(self.engine, "connect")
        def foreign_keys(connection, _):
            connection.execute("PRAGMA foreign_keys=ON")
        self.app = create_app(config=self.config, test_engine=self.engine)
        self.app.state.integration_base.metadata.create_all(self.engine)
        self.factory = self.app.state.integration_session_factory
        from app import models
        from app import ai_event_models
        from app.core.security import create_access_token, hash_password
        self.models, self.ai_models = models, ai_event_models
        global _PASSWORD_HASH
        if _PASSWORD_HASH is None:
            _PASSWORD_HASH = hash_password("SyntheticUnitOnly123!")
        with self.factory() as db:
            role = models.Role(name="viewer")
            admin = models.Role(name="admin")
            db.add_all([role, admin])
            db.flush()
            db.add_all([
                models.User(id=1, username="unitviewer", email="viewer@example.invalid", full_name="Unit viewer",
                            password_hash=_PASSWORD_HASH, roles=[role]),
                models.User(id=2, username="unitadmin", email="admin@example.invalid", full_name="Unit admin",
                            password_hash=_PASSWORD_HASH, roles=[admin]),
                models.Artwork(id=1, inventory_code="SYNTHETIC_TEST", title="Synthetic", artist="Test"),
            ])
            db.flush()
            db.add(models.Device(id=1, device_code="SYNTHETIC_TEST", name="Synthetic", artwork_id=1))
            db.commit()
        self.human_token = create_access_token("1")
        self.admin_token = create_access_token("2")
        self.producer = self.config.producers[0]
        self.client = None
        self.network_guard = patch.object(socket, "create_connection",
                                          side_effect=AssertionError("External network forbidden in unit tests"))
        self.network_guard.start()
        if http:
            self.client = TestClient(self.app, raise_server_exceptions=False)
            self.client.__enter__()

    def event_dict(self, **changes):
        value = {"schema_version": "1", "event_id": str(uuid4()), "producer_id": "unit-producer",
                 "producer_instance_id": self.instance, "source_event_id": "42",
                 "data_origin": "SYNTHETIC_TEST", "event_type": "AI_CONTACT_SUSPECTED_IN_ROI",
                 "detected_at": "2026-10-27T10:00:00Z", "time_source": "ALERT_DECISION",
                 "artwork_id": 1, "device_id": 1, "scores": {"object_contact": 0.91},
                 "evidence_ref": {"status": "PENDING"}}
        value.update(changes)
        return value

    def event(self, **changes):
        from app.ai_event_schemas import AiEventIn
        return AiEventIn.model_validate(self.event_dict(**changes))

    def jpeg(self, color="white"):
        from PIL import Image
        stream = io.BytesIO()
        Image.new("RGB", (16, 16), color).save(stream, "JPEG")
        return stream.getvalue()

    def counts(self):
        from sqlalchemy import func, select
        with self.factory() as db:
            return tuple(db.scalar(select(func.count()).select_from(model)) for model in (
                self.ai_models.AiEventReceipt, self.models.Alert, self.models.Evidence,
                self.models.AlertHistory, self.models.EvidenceHistory, self.models.AuditLog,
                self.ai_models.AiEventAttachment, self.models.EvidenceMedia))

    @property
    def producer_headers(self):
        return {"X-ArtGuard-Producer-Key": self.token}

    @property
    def human_headers(self):
        return {"Authorization": "Bearer " + self.human_token}

    def close(self):
        try:
            if self.client is not None:
                self.client.__exit__(None, None, None)
            else:
                self.engine.dispose()
        finally:
            self.network_guard.stop()
            remove_app_modules()
