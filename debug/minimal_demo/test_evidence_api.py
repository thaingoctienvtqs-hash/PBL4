"""Step A: SYNTHETIC_TEST, synchronous Evidence routes, SQLite :memory: only.

Run ONLY this file with the backend interpreter and -B:
python -B -X utf8 debug/minimal_demo/test_evidence_api.py -v

No TestClient, ASGITransport, server, event loop, camera or model is used.
Payload/dependency tests are unit tests, NOT HTTP 401/403/422 integration tests.
BaselineReproductionTests are explicit pre-fix diagnostics; load_tests excludes
them from the normal regression suite. Never use them as post-fix success tests.
The audit hook is a supplementary observer, NOT a native network sandbox.
Its active state and every monkeypatch are cleaned up after success or failure.
"""
import ast
import builtins
import importlib
import importlib.abc
import inspect
import json
import os
import sys
import types
import unittest
from contextlib import ExitStack, contextmanager
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
BACKEND = ROOT / "web" / "backend"
VENV_SITE = BACKEND / ".venv" / "Lib" / "site-packages"
FIXED = datetime(2026, 1, 1, 12, 0, 0)
SYNTHETIC_NOTE = "SYNTHETIC_TEST ch\u1ea1m: ghi ch\u00fa"
_APP_SOURCES = {
    "app": "app/__init__.py",
    "app.api": "app/api/__init__.py",
    "app.core": "app/core/__init__.py",
    "app.api.evidence": "app/api/evidence.py",
    "app.audit": "app/audit.py",
    "app.models": "app/models.py",
    "app.schemas": "app/schemas.py",
    "app.dependencies": "app/dependencies.py",
    "app.core.security": "app/core/security.py",
    "app.core.settings": "app/core/settings.py",
    "app.db": "app/db.py",
}
_RISKY_ROOTS = {
    "pyodbc", "pymssql", "mssql_python", "torch", "detectron2",
    "cv2", "uvicorn", "pytest",
}
_STATE = {
    "active": False, "restored": True, "unexpected": [],
    "expected_rejections": [], "expecting": 0, "memory_connections": [],
    "engine_urls": [], "origins": {}, "static_audit": [],
}
_WRITE_FLAGS = os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC | os.O_APPEND
_STACK = None


class IsolationViolation(AssertionError):
    pass


def _blocked(operation):
    key = "expected_rejections" if _STATE["expecting"] else "unexpected"
    _STATE[key].append(operation)
    raise IsolationViolation("BLOCKED unsafe operation: " + operation)


@contextmanager
def expected_rejection():
    _STATE["expecting"] += 1
    try:
        yield
    finally:
        _STATE["expecting"] -= 1


def _audit_guard(event, args):
    if not _STATE["active"]:
        return
    if event == "open":
        mode, flags = args[1:3]
        if (isinstance(mode, str) and any(c in mode for c in "wax+")) or (
            isinstance(flags, int) and flags & _WRITE_FLAGS
        ):
            _blocked("file_write:" + str(args[0]))
        if isinstance(args[0], (str, bytes)):
            name = os.fsdecode(args[0]).replace("\\", "/").rsplit("/", 1)[-1]
            if name in {".env", ".netrc"}:
                _blocked("secret_config_read")
    elif event == "sqlite3.connect":
        if args[0] != ":memory:":
            _blocked("sqlite_not_memory")
        _STATE["memory_connections"].append(":memory:")
    elif event in {
        "socket.connect", "socket.bind", "socket.getaddrinfo",
        "socket.gethostbyname", "socket.gethostbyaddr", "socket.sendto",
        "socket.sendmsg", "subprocess.Popen", "os.system", "os.mkdir",
        "os.remove", "os.rmdir", "os.rename", "os.chmod", "os.utime",
        "winreg.CreateKey", "winreg.SetValue", "winreg.DeleteKey",
        "winreg.DeleteValue",
    }:
        _blocked(event)


def _check_import(name, fromlist=()):
    if name.split(".")[0] in _RISKY_ROOTS:
        _blocked("import:" + name)
    if name == "app.main" or (name == "app" and fromlist and "main" in fromlist):
        _blocked("import:app.main")


class _RiskyImportFinder(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        _check_import(fullname)
        return None


def _remove_app_modules():
    for name in list(sys.modules):
        if name == "app" or name.startswith("app."):
            sys.modules.pop(name, None)


def _restore_isolation():
    if _STATE["restored"]:
        return
    # Python cannot remove an audit hook. Disable its action before restoration.
    _STATE["active"] = False
    try:
        _STACK.close()
    finally:
        _STATE["restored"] = True
    print("STEP_A_CLEANUP " + json.dumps({
        "patches_restored": True, "audit_hook_active": _STATE["active"],
        "app_modules_remaining": sorted(
            n for n in sys.modules if n == "app" or n.startswith("app.")),
    }), flush=True)


def setUpModule():
    global _STACK, _DB_DOUBLE, _SETTINGS_DOUBLE, TestBase
    global sqlalchemy, Session, sessionmaker, StaticPool, select, func
    global Evidence, EvidenceHistory, EvidenceMedia, AuditLog, User
    global EvidenceDetail, EvidenceHistoryOut, EvidenceStatusUpdate, ValidationError
    global HTTPException, HTTPAuthorizationCredentials, evidence_api, app_dependencies
    assert sys.dont_write_bytecode, "BLOCKED: run with -B"
    assert not any(n == "app" or n.startswith("app.") for n in sys.modules), (
        "BLOCKED: pre-existing application modules")
    assert not any(n.split(".")[0] in _RISKY_ROOTS for n in sys.modules), (
        "BLOCKED: pre-existing risky modules")
    _STACK = ExitStack()
    _STATE.update(active=True, restored=False)
    unittest.addModuleCleanup(_restore_isolation)
    sys.addaudithook(_audit_guard)
    previous_path = sys.path[:]
    _STACK.callback(lambda: sys.path.__setitem__(slice(None), previous_path))
    sys.path.append(str(BACKEND))
    original_import = builtins.__import__

    def guarded_import(name, globals=None, locals=None, fromlist=(), level=0):
        _check_import(name, fromlist)
        return original_import(name, globals, locals, fromlist, level)

    _STACK.enter_context(patch.object(builtins, "__import__", guarded_import))
    _STACK.enter_context(patch.object(sys, "meta_path", [_RiskyImportFinder(), *sys.meta_path]))

    # Read the actual closure before importing ANY application module.
    for name, relative in _APP_SOURCES.items():
        tree = ast.parse((BACKEND / relative).read_bytes(), filename=relative)
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                assert not node.level, "BLOCKED: unreviewed relative application import"
                if node.module and node.module.startswith("app"):
                    assert node.module in _APP_SOURCES, "BLOCKED: unreviewed application import"
            elif isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name.startswith("app"):
                        assert alias.name in _APP_SOURCES, "BLOCKED: unreviewed application import"
        if name in {"app", "app.api", "app.core"}:
            assert all(
                isinstance(n, ast.Expr) and isinstance(n.value, ast.Constant)
                and isinstance(n.value.value, str) for n in tree.body
            ), "BLOCKED: package initializer has side effects"
        _STATE["static_audit"].append({
            "module": name,
            "action": "STUB_BEFORE_IMPORT" if name in {"app.db", "app.core.settings"}
            else "REVIEWED_SOURCE",
        })
    router_tree = ast.parse((BACKEND / "app/api/evidence.py").read_bytes())
    for name in ("get_evidence", "update_evidence_status"):
        node = next(n for n in router_tree.body if getattr(n, "name", None) == name)
        assert isinstance(node, ast.FunctionDef), "BLOCKED: asynchronous route requires review"
    print("STEP_A_STATIC_IMPORT_AUDIT " + json.dumps(_STATE["static_audit"]), flush=True)

    import fastapi
    import starlette
    import pydantic
    import anyio
    import sqlalchemy as sa
    from fastapi import HTTPException as HttpError
    from fastapi.security import HTTPAuthorizationCredentials as Credentials
    from pydantic import ValidationError as PayloadError
    from sqlalchemy import create_engine, select as sql_select, func as sql_func
    from sqlalchemy.orm import DeclarativeBase, Session as DbSession, sessionmaker as factory
    from sqlalchemy.pool import StaticPool as MemoryPool

    sqlalchemy, Session, sessionmaker, StaticPool = sa, DbSession, factory, MemoryPool
    select, func = sql_select, sql_func
    HTTPException, HTTPAuthorizationCredentials, ValidationError = HttpError, Credentials, PayloadError
    for module in (fastapi, starlette, sa, pydantic, anyio):
        origin = Path(module.__file__).resolve()
        assert origin.is_relative_to(VENV_SITE.resolve()), "BLOCKED: wrong import origin"
        _STATE["origins"][module.__name__] = str(origin)
    print("STEP_A_IMPORT_ORIGINS " + json.dumps(_STATE["origins"], sort_keys=True), flush=True)

    def memory_engine(url="sqlite://", **kwargs):
        if str(url) not in {"sqlite://", "sqlite:///:memory:"} or "creator" in kwargs:
            _blocked("sqlalchemy_not_memory")
        _STATE["engine_urls"].append(str(url))
        return create_engine(url, **kwargs)

    globals()["memory_engine"] = memory_engine
    _STACK.enter_context(patch.object(sa, "create_engine", memory_engine))

    class MemoryBase(DeclarativeBase):
        pass

    TestBase = MemoryBase

    def forbidden_default_db():
        _blocked("application_default_get_db")
        yield None

    _DB_DOUBLE = types.ModuleType("app.db")
    _DB_DOUBLE.Base = TestBase
    _DB_DOUBLE.get_db = forbidden_default_db
    _DB_DOUBLE.engine = None
    _DB_DOUBLE.SessionLocal = forbidden_default_db
    _SETTINGS_DOUBLE = types.ModuleType("app.core.settings")
    _SETTINGS_DOUBLE.settings = types.SimpleNamespace(
        app_env="testing", jwt_secret_key="SYNTHETIC_TEST_NOT_A_SERVICE_SECRET",
        jwt_expire_minutes=60,
    )
    _STACK.callback(_remove_app_modules)
    sys.modules["app.db"] = _DB_DOUBLE
    sys.modules["app.core.settings"] = _SETTINGS_DOUBLE

    from app.api import evidence as router_module
    from app import dependencies as dependencies_module
    from app.models import Evidence as Ev, EvidenceHistory as History
    from app.models import EvidenceMedia as Media, AuditLog as Audit, User as Account
    from app.schemas import EvidenceDetail as Detail, EvidenceHistoryOut as HistoryOut
    from app.schemas import EvidenceStatusUpdate as StatusUpdate

    evidence_api, app_dependencies = router_module, dependencies_module
    Evidence, EvidenceHistory, EvidenceMedia, AuditLog, User = Ev, History, Media, Audit, Account
    EvidenceDetail, EvidenceHistoryOut, EvidenceStatusUpdate = Detail, HistoryOut, StatusUpdate
    assert Path(evidence_api.__file__).resolve() == (BACKEND / "app/api/evidence.py").resolve()
    assert sys.modules["app.db"] is _DB_DOUBLE
    assert sys.modules["app.core.settings"] is _SETTINGS_DOUBLE
    assert "app.main" not in sys.modules and "pyodbc" not in sys.modules
    assert "starlette.testclient" not in sys.modules and "httpx" not in sys.modules
    print("STEP_A_MODE synchronous direct routes; no HTTP transport or event loop", flush=True)


def tearDownModule():
    try:
        assert not _STATE["unexpected"], repr(_STATE["unexpected"])
        assert "pyodbc" not in sys.modules and "app.main" not in sys.modules
        print("STEP_A_SAFETY " + json.dumps({
            "unexpected_operations": _STATE["unexpected"],
            "expected_rejections": _STATE["expected_rejections"],
            "memory_connections": len(_STATE["memory_connections"]),
            "engine_urls": sorted(set(_STATE["engine_urls"])),
            "real_db_module_executed": False,
            "real_settings_executed": False,
            "http_end_to_end": "NOT TESTED",
            "network_sandbox_claim": False,
            "fixture": "SYNTHETIC_TEST",
        }), flush=True)
    finally:
        _restore_isolation()


class MemoryFixture(unittest.TestCase):
    def setUp(self):
        self.engine = memory_engine(
            "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
        self.addCleanup(self.engine.dispose)
        with self.engine.connect() as connection:
            connection.exec_driver_sql("PRAGMA foreign_keys=ON")
            connection.exec_driver_sql("PRAGMA temp_store=MEMORY")
        TestBase.metadata.create_all(self.engine)
        self.factory = sessionmaker(bind=self.engine, autoflush=False, expire_on_commit=False)
        with self.factory() as db:
            db.add(User(
                id=1, username="SYNTHETIC_TEST", email="fixture@example.com",
                full_name="SYNTHETIC_TEST Operator", password_hash="NOT_A_REAL_PASSWORD_HASH",
                is_active=True, created_at=FIXED, updated_at=FIXED))
            for ident in (1, 2):
                db.add(Evidence(
                    id=ident, evidence_code="SYNTHETIC_TEST_" + str(ident),
                    event_type="touching", severity="medium", processing_status="pending",
                    source="demo", detected_at=FIXED, created_at=FIXED, updated_at=FIXED))
            db.commit()

    def user(self, role="operator"):
        return types.SimpleNamespace(
            id=1, full_name="SYNTHETIC_TEST Operator",
            roles=[types.SimpleNamespace(name=role)])

    def detail(self, ident=1):
        with self.factory() as db:
            return evidence_api.get_evidence(evidence_id=ident, _=self.user(), db=db)

    def update(self, status="reviewed", note="SYNTHETIC_TEST note", ident=1, user=None):
        # No fake authorization, exception mapping or rollback in this helper.
        payload = EvidenceStatusUpdate(processing_status=status, note=note)
        with self.factory() as db:
            return evidence_api.update_evidence_status(
                evidence_id=ident, payload=payload,
                user=self.user() if user is None else user, db=db)

    def snapshot(self):
        # Fresh session after route session closure; never rely on its identity map.
        with self.factory() as db:
            evidences = [(e.id, e.processing_status, e.updated_at)
                         for e in db.scalars(select(Evidence).order_by(Evidence.id))]
            history = [(h.id, h.evidence_id, h.user_id, h.from_status,
                        h.to_status, h.note, h.changed_at)
                       for h in db.scalars(select(EvidenceHistory).order_by(EvidenceHistory.id))]
            audit = [(a.id, a.user_id, a.action, a.entity_type,
                      a.entity_id, a.detail, a.created_at)
                     for a in db.scalars(select(AuditLog).order_by(AuditLog.id))]
            return evidences, history, audit

    def seed_history(self, ident, when, row_id, user_id=1, note="SYNTHETIC_TEST history"):
        with self.factory() as db:
            db.add(EvidenceHistory(
                id=row_id, evidence_id=ident, user_id=user_id,
                from_status="pending", to_status="reviewed", note=note, changed_at=when))
            db.commit()

    def assert_rollback(self, owner, attribute, replacement, exception=RuntimeError):
        before = self.snapshot()
        original = Session.rollback
        calls = []

        def rollback(db, *args, **kwargs):
            calls.append(True)
            return original(db, *args, **kwargs)

        with patch.object(Session, "rollback", new=rollback), patch.object(owner, attribute, replacement):
            with self.assertRaises(exception):
                self.update()
        self.assertEqual(self.snapshot(), before)
        self.assertGreaterEqual(len(calls), 1, "route must explicitly rollback")


class IsolationTests(MemoryFixture):
    def test_real_db_and_settings_are_never_imported(self):
        self.assertIs(sys.modules["app.db"], _DB_DOUBLE)
        self.assertIs(sys.modules["app.core.settings"], _SETTINGS_DOUBLE)
        self.assertFalse(hasattr(_DB_DOUBLE, "__file__"))
        self.assertFalse(hasattr(_SETTINGS_DOUBLE, "__file__"))
        self.assertIs(evidence_api.get_db, _DB_DOUBLE.get_db)
        self.assertIs(app_dependencies.get_db, _DB_DOUBLE.get_db)
        self.assertNotIn("app.main", sys.modules)
        self.assertNotIn("pyodbc", sys.modules)

    def test_only_memory_database_and_no_transport(self):
        self.assertEqual(str(self.engine.url), "sqlite://")
        self.assertFalse(self.factory.kw["autoflush"])
        self.assertFalse(self.factory.kw["expire_on_commit"])
        with self.engine.connect() as connection:
            databases = connection.exec_driver_sql("PRAGMA database_list").all()
            self.assertIn((0, "main", ""), databases)
            self.assertTrue(all(name in {"main", "temp"} and path == ""
                                for _, name, path in databases))
            self.assertEqual(connection.exec_driver_sql("PRAGMA temp_store").scalar(), 2)
            self.assertEqual(connection.exec_driver_sql("PRAGMA foreign_keys").scalar(), 1)
        self.assertTrue(_STATE["memory_connections"])
        self.assertEqual(set(_STATE["memory_connections"]), {":memory:"})
        self.assertNotIn("starlette.testclient", sys.modules)
        self.assertNotIn("httpx", sys.modules)

    def test_nonmemory_engine_rejected_before_factory(self):
        before = len(_STATE["memory_connections"])
        with expected_rejection(), self.assertRaisesRegex(IsolationViolation, "sqlalchemy_not_memory"):
            sqlalchemy.create_engine("mssql+pyodbc://SYNTHETIC_TEST")
        self.assertEqual(len(_STATE["memory_connections"]), before)

    def test_real_pyodbc_import_rejected_without_loading(self):
        with expected_rejection(), self.assertRaisesRegex(IsolationViolation, "import:pyodbc"):
            importlib.import_module("pyodbc")
        self.assertNotIn("pyodbc", sys.modules)

    def test_default_application_session_provider_is_unusable(self):
        with expected_rejection(), self.assertRaisesRegex(IsolationViolation, "application_default_get_db"):
            next(_DB_DOUBLE.get_db())

    def test_get_patch_are_sync_and_real_endpoints(self):
        for name, method, path in (
            ("get_evidence", "GET", "/evidences/{evidence_id}"),
            ("update_evidence_status", "PATCH", "/evidences/{evidence_id}/status"),
        ):
            endpoint = getattr(evidence_api, name)
            self.assertFalse(inspect.iscoroutinefunction(endpoint))
            route = next(r for r in evidence_api.router.routes
                         if r.path == path and method in r.methods)
            self.assertIs(route.endpoint, endpoint)
            self.assertIs(route.response_model, EvidenceDetail)


class EvidenceCoreTests(MemoryFixture):
    def test_get_empty_history(self):
        detail = self.detail()
        self.assertIsInstance(detail, EvidenceDetail)
        self.assertEqual(detail.history, [])

    def test_get_multiple_history_ordered_by_time_then_id_desc(self):
        self.seed_history(1, FIXED + timedelta(days=2), 10)
        self.seed_history(1, FIXED + timedelta(days=2), 11)
        self.seed_history(1, FIXED + timedelta(days=1), 12)
        self.assertEqual([h.id for h in self.detail().history], [11, 10, 12])

    def test_get_history_cannot_leak_other_evidence(self):
        self.seed_history(1, FIXED, 10)
        self.seed_history(2, FIXED + timedelta(days=9), 99)
        self.assertEqual([h.id for h in self.detail().history], [10])

    def test_get_nullable_history_user(self):
        self.seed_history(1, FIXED, 10, user_id=None)
        self.assertIsNone(self.detail().history[0].user_name)

    def test_get_does_not_write(self):
        before = self.snapshot()
        self.assertIsInstance(self.detail(), EvidenceDetail)
        self.assertEqual(self.snapshot(), before)

    def test_get_preserves_public_response_schema_and_media(self):
        with self.factory() as db:
            db.add(EvidenceMedia(
                evidence_id=1, media_type="image", file_path="SYNTHETIC_TEST_NOT_OPENED.jpg",
                file_size=7, mime_type="image/jpeg", created_at=FIXED))
            db.commit()
        detail = self.detail()
        body = detail.model_dump(mode="json")
        self.assertEqual(set(body), set(EvidenceDetail.model_fields))
        self.assertTrue(detail.has_image)
        self.assertFalse(detail.has_video)
        self.assertEqual(body["media"][0]["file_path"], "SYNTHETIC_TEST_NOT_OPENED.jpg")
        EvidenceDetail.model_validate(body)

    def test_patch_then_get_consistent_and_history_has_real_id(self):
        detail = self.update(note=SYNTHETIC_NOTE)
        self.assertEqual(detail.processing_status, "reviewed")
        self.assertEqual(len(detail.history), 1)
        self.assertGreater(detail.history[0].id, 0)
        self.assertEqual(detail.history[0].note, SYNTHETIC_NOTE)
        self.assertEqual(detail.history[0].user_name, "SYNTHETIC_TEST Operator")
        self.assertEqual(self.detail().model_dump(), detail.model_dump())

    def test_patch_persists_history_audit_and_updated_at(self):
        self.assertEqual(self.update().processing_status, "reviewed")
        evidences, history, audit = self.snapshot()
        self.assertEqual(evidences[0][1], "reviewed")
        self.assertGreater(evidences[0][2], FIXED)
        self.assertEqual(len(history), 1)
        self.assertEqual(history[0][3:6], ("pending", "reviewed", "SYNTHETIC_TEST note"))
        self.assertEqual(len(audit), 1)
        self.assertEqual(audit[0][2:6], ("update_status", "evidence", 1, "reviewed"))

    def test_same_status_each_note_history_audit_and_timestamp_are_written(self):
        previous_time = FIXED
        notes = ("  SYNTHETIC_TEST ghi ch\u00fa m\u1ed9t  ", "SYNTHETIC_TEST ghi ch\u00fa hai")
        for index, note in enumerate(notes, 1):
            stamp = FIXED + timedelta(days=index)
            with patch.object(evidence_api, "datetime", types.SimpleNamespace(utcnow=lambda: stamp)):
                detail = self.update(status="reviewed", note=note)
            evidences, history, audit = self.snapshot()
            self.assertEqual(detail.history[0].note, note)
            self.assertEqual(evidences[0][2], stamp)
            self.assertGreater(evidences[0][2], previous_time)
            self.assertEqual(len(history), index)
            self.assertEqual(len(audit), index)
            self.assertEqual(history[-1][3:5],
                             ("pending" if index == 1 else "reviewed", "reviewed"))
            self.assertEqual(history[-1][5], note)
            previous_time = evidences[0][2]

    def test_same_status_without_note_is_not_noop(self):
        self.update()
        self.update(note=None)
        _, history, audit = self.snapshot()
        self.assertEqual(len(history), 2)
        self.assertEqual(len(audit), 2)
        self.assertIsNone(history[-1][5])
        self.assertEqual(history[-1][3:5], ("reviewed", "reviewed"))

    def test_empty_note_is_not_normalized(self):
        self.update(note="")
        self.assertEqual(self.snapshot()[1][0][5], "")

    def test_note_500_characters_is_preserved(self):
        self.update(note="n" * 500)
        self.assertEqual(self.snapshot()[1][0][5], "n" * 500)

    def test_payload_note_501_characters_rejected_without_write(self):
        before = self.snapshot()
        with self.assertRaises(ValidationError):
            self.update(note="n" * 501)
        self.assertEqual(self.snapshot(), before)

    def test_payload_invalid_status_rejected_without_write(self):
        before = self.snapshot()
        with self.assertRaises(ValidationError):
            self.update(status="pending")
        self.assertEqual(self.snapshot(), before)

    def test_patch_public_response_schema_unchanged(self):
        detail = self.update()
        self.assertEqual(set(detail.model_dump()), set(EvidenceDetail.model_fields))
        EvidenceDetail.model_validate(detail.model_dump(mode="json"))

    def test_existing_writer_roles_explicit_users_can_update(self):
        checker = inspect.signature(evidence_api.update_evidence_status).parameters["user"].default.dependency
        for role in ("admin", "manager", "operator"):
            user = self.user(role)
            self.assertIs(checker(user=user), user)
            self.assertEqual(self.update(user=user).processing_status, "reviewed")
        self.assertEqual(len(self.snapshot()[1]), 3)

    def test_missing_get_raises_404_without_write(self):
        before = self.snapshot()
        with self.assertRaises(HTTPException) as caught:
            self.detail(ident=999)
        self.assertEqual(caught.exception.status_code, 404)
        self.assertEqual(self.snapshot(), before)

    def test_missing_patch_raises_404_without_write(self):
        before = self.snapshot()
        with self.assertRaises(HTTPException) as caught:
            self.update(ident=999)
        self.assertEqual(caught.exception.status_code, 404)
        self.assertEqual(self.snapshot(), before)

    def test_response_construction_error_rolls_back(self):
        def fail(*args, **kwargs):
            raise RuntimeError("SYNTHETIC_TEST detail failure")
        self.assert_rollback(evidence_api, "_evidence_detail", fail)

    def test_real_pydantic_validation_error_rolls_back(self):
        original = EvidenceHistoryOut

        def invalid(**values):
            values["id"] = "SYNTHETIC_TEST_NOT_AN_INTEGER"
            return original(**values)
        self.assert_rollback(
            evidence_api, "EvidenceHistoryOut", invalid, exception=ValidationError)

    def test_flush_error_rolls_back(self):
        def fail(*args, **kwargs):
            raise RuntimeError("SYNTHETIC_TEST flush failure")
        self.assert_rollback(Session, "flush", fail)

    def test_refresh_error_rolls_back(self):
        def fail(*args, **kwargs):
            raise RuntimeError("SYNTHETIC_TEST refresh failure")
        self.assert_rollback(Session, "refresh", fail)

    def test_history_query_error_rolls_back(self):
        original = Session.scalars

        def fail(db, statement, *args, **kwargs):
            if any(c.get("entity") is EvidenceHistory for c in statement.column_descriptions):
                raise RuntimeError("SYNTHETIC_TEST history SELECT failure")
            return original(db, statement, *args, **kwargs)
        self.assert_rollback(Session, "scalars", fail)

    def test_audit_error_rolls_back(self):
        def fail(*args, **kwargs):
            raise RuntimeError("SYNTHETIC_TEST audit failure")
        self.assert_rollback(evidence_api, "record_audit", fail)

    def test_precommit_commit_error_rolls_back(self):
        def fail(*args, **kwargs):
            raise RuntimeError("SYNTHETIC_TEST precommit failure")
        self.assert_rollback(Session, "commit", fail)

    def test_success_validates_before_commit_and_no_refresh_after(self):
        order = []
        originals = {name: getattr(Session, name) for name in ("flush", "refresh", "commit")}
        detail = evidence_api._evidence_detail

        def wrap(name):
            def call(db, *args, **kwargs):
                order.append(name)
                return originals[name](db, *args, **kwargs)
            return call

        def observed_detail(*args, **kwargs):
            order.append("detail")
            return detail(*args, **kwargs)

        with patch.object(Session, "flush", wrap("flush")), patch.object(Session, "refresh", wrap("refresh")), \
             patch.object(Session, "commit", wrap("commit")), patch.object(evidence_api, "_evidence_detail", observed_detail):
            result = self.update()
        self.assertIsInstance(result, EvidenceDetail)
        self.assertEqual(order.count("commit"), 1)
        self.assertLess(order.index("flush"), order.index("detail"))
        self.assertLess(order.index("refresh"), order.index("detail"))
        self.assertLess(order.index("detail"), order.index("commit"))
        self.assertNotIn("refresh", order[order.index("commit") + 1:])
        self.assertNotIn("detail", order[order.index("commit") + 1:])


class DependencyUnitTests(MemoryFixture):
    def test_route_dependency_bindings_preserved(self):
        get_params = inspect.signature(evidence_api.get_evidence).parameters
        patch_params = inspect.signature(evidence_api.update_evidence_status).parameters
        self.assertIs(get_params["_"].default.dependency, app_dependencies.get_current_user)
        self.assertIs(get_params["db"].default.dependency, _DB_DOUBLE.get_db)
        self.assertIs(patch_params["db"].default.dependency, _DB_DOUBLE.get_db)
        checker = patch_params["user"].default.dependency
        self.assertIs(inspect.signature(checker).parameters["user"].default.dependency,
                      app_dependencies.get_current_user)

    def test_missing_credentials_dependency_raises_401_without_write(self):
        before = self.snapshot()
        with self.factory() as db, self.assertRaises(HTTPException) as caught:
            app_dependencies.get_current_user(credentials=None, db=db)
        self.assertEqual(caught.exception.status_code, 401)
        self.assertEqual(caught.exception.headers, {"WWW-Authenticate": "Bearer"})
        self.assertEqual(self.snapshot(), before)

    def test_invalid_token_dependency_raises_401_without_write(self):
        before = self.snapshot()
        credentials = HTTPAuthorizationCredentials(scheme="Bearer", credentials="SYNTHETIC_TEST.invalid")
        with self.factory() as db, self.assertRaises(HTTPException) as caught:
            app_dependencies.get_current_user(credentials=credentials, db=db)
        self.assertEqual(caught.exception.status_code, 401)
        self.assertEqual(self.snapshot(), before)

    def test_actual_patch_role_dependency_rejects_viewer_403(self):
        before = self.snapshot()
        checker = inspect.signature(evidence_api.update_evidence_status).parameters["user"].default.dependency
        with self.assertRaises(HTTPException) as caught:
            checker(user=self.user("viewer"))
        self.assertEqual(caught.exception.status_code, 403)
        self.assertEqual(self.snapshot(), before)

    def test_actual_patch_role_dependency_allows_existing_writer_roles(self):
        checker = inspect.signature(evidence_api.update_evidence_status).parameters["user"].default.dependency
        for role in ("admin", "manager", "operator"):
            with self.subTest(role=role):
                user = self.user(role)
                self.assertIs(checker(user=user), user)

    def test_actual_patch_role_dependency_rejects_empty_roles(self):
        checker = inspect.signature(evidence_api.update_evidence_status).parameters["user"].default.dependency
        user = self.user()
        user.roles = []
        with self.assertRaises(HTTPException) as caught:
            checker(user=user)
        self.assertEqual(caught.exception.status_code, 403)


class BaselineReproductionTests(MemoryFixture):
    """Pre-fix diagnosis only; run explicitly, excluded by load_tests."""

    def test_original_get_reproduces_missing_history_attribute(self):
        before = self.snapshot()
        with self.assertRaisesRegex(AttributeError, "history"):
            self.detail()
        self.assertEqual(self.snapshot(), before)

    def test_original_patch_commits_before_missing_history_error(self):
        with self.assertRaisesRegex(AttributeError, "history"):
            self.update()
        evidences, history, audit = self.snapshot()
        self.assertEqual(evidences[0][1], "reviewed")
        self.assertEqual(len(history), 1)
        self.assertEqual(len(audit), 1)


def load_tests(loader, standard_tests, pattern):
    # Keep pre-fix diagnostic expectations separate from regression assertions.
    return unittest.TestSuite(loader.loadTestsFromTestCase(cls) for cls in (
        IsolationTests, EvidenceCoreTests, DependencyUnitTests,
    ))


if __name__ == "__main__":
    unittest.main(verbosity=2)
