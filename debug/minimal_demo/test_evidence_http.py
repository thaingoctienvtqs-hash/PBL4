"""Step A HTTP: SYNTHETIC_TEST Evidence requests through FastAPI/Starlette.

Run alone with the backend Python, -B and the existing external httpx dependency:
python -B -X utf8 debug/minimal_demo/test_evidence_http.py -v

Only app.db/settings and the request DB provider are replaced. Real bearer/JWT,
role dependencies, routes, models, payload validation and serialization execute.
No app.main, server, production DB, camera or model is used.
Windows asyncio self-pipe socketpair is observed, NOT given an exemption window.
This bounded test setup is not a native network sandbox or production E2E test.
"""
import ast
import builtins
import importlib.abc
import inspect
import json
import os
import socket
import sys
import threading
import types
import unittest
from contextlib import ExitStack
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
BACKEND = ROOT / "web" / "backend"
SITE = BACKEND / ".venv" / "Lib" / "site-packages"
DEPS = Path(r"C:\Users\LEGION\pbl4_test_deps_stepA_20261022T112244884173Z_9118a5b5")
FIXED = datetime(2026, 1, 1, 12, 0)
SYNTHETIC_KEY = "SYNTHETIC_TEST_ONLY_LOCAL_HMAC_KEY_NOT_A_SERVICE_SECRET_20261024"
NOTE = "SYNTHETIC_TEST ch\u1ea1m tranh: ghi ch\u00fa"
APP_SOURCES = {
    "app": "app/__init__.py", "app.api": "app/api/__init__.py",
    "app.core": "app/core/__init__.py", "app.api.evidence": "app/api/evidence.py",
    "app.audit": "app/audit.py", "app.models": "app/models.py",
    "app.schemas": "app/schemas.py", "app.dependencies": "app/dependencies.py",
    "app.core.security": "app/core/security.py", "app.db": "app/db.py",
    "app.core.settings": "app/core/settings.py",
}
RISKY = {"pyodbc", "pymssql", "mssql_python", "torch", "detectron2", "cv2", "uvicorn", "pytest"}
OBS = {
    "active": False, "restored": True, "blocked": [], "socket_events": [],
    "asgi_requests": [], "memory_connections": 0, "engines": 0, "disposed": 0,
    "clients": 0, "closed_clients": 0, "request_sessions": 0, "origins": {},
}
STACK = None
FALLBACK_CODE = socket._fallback_socketpair.__code__
WRITE_FLAGS = os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC | os.O_APPEND


class IsolationError(AssertionError):
    pass


def blocked(operation):
    OBS["blocked"].append(operation)
    raise IsolationError("BLOCKED: " + operation)


def audit_observer(event, args):
    if not OBS["active"]:
        return
    if event == "open":
        mode, flags = args[1:3]
        if (isinstance(mode, str) and any(c in mode for c in "wax+")) or (
            isinstance(flags, int) and flags & WRITE_FLAGS
        ):
            blocked("file_write")
        if isinstance(args[0], (str, bytes)):
            if os.fsdecode(args[0]).replace("\\", "/").rsplit("/", 1)[-1] in {".env", ".netrc"}:
                blocked("production_or_secret_config_read")
    elif event == "sqlite3.connect":
        if args[0] != ":memory:":
            blocked("sqlite_not_memory")
        OBS["memory_connections"] += 1
    elif event in {"socket.bind", "socket.connect"}:
        # Observation only: no socketpair wrapper, permission window or whitelist.
        caller = sys._getframe(1)
        current_socket, address = args
        variable = "lsock" if event == "socket.bind" else "csock"
        exact_owner = (
            caller.f_code is FALLBACK_CODE
            and caller.f_locals.get(variable) is current_socket
        )
        target_matches = None
        if event == "socket.connect" and exact_owner:
            target_matches = tuple(address) == tuple(
                caller.f_locals["lsock"].getsockname()[:2])
        OBS["socket_events"].append({
            "event": event, "address": list(address), "thread": threading.get_ident(),
            "caller_file": caller.f_code.co_filename, "caller_line": caller.f_lineno,
            "exact_fallback_owner": exact_owner, "listener_target_matches": target_matches,
        })
    elif event in {
        "socket.getaddrinfo", "socket.gethostbyname", "socket.gethostbyaddr",
        "socket.sendto", "socket.sendmsg", "subprocess.Popen", "os.system",
        "os.mkdir", "os.remove", "os.rmdir", "os.rename", "os.chmod", "os.utime",
        "winreg.CreateKey", "winreg.SetValue", "winreg.DeleteKey", "winreg.DeleteValue",
    }:
        blocked(event)


def check_import(name, fromlist=()):
    if name.split(".")[0] in RISKY:
        blocked("import:" + name)
    if name == "app.main" or (name == "app" and fromlist and "main" in fromlist):
        blocked("import:app.main")


class ImportFinder(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        check_import(fullname)
        return None


def remove_app_modules():
    for name in list(sys.modules):
        if name == "app" or name.startswith("app."):
            sys.modules.pop(name, None)


def cleanup_module():
    if OBS["restored"]:
        return
    OBS["active"] = False
    try:
        STACK.close()
    finally:
        OBS["restored"] = True
    print("STEP_A_HTTP_CLEANUP " + json.dumps({
        "restored": True, "audit_active": OBS["active"],
        "app_modules_remaining": sorted(
            n for n in sys.modules if n == "app" or n.startswith("app.")),
    }), flush=True)


def verify_ipc(events):
    for row in events:
        assert row["exact_fallback_owner"], "unexplained socket operation: " + repr(row)
        assert row["address"][0] in {"127.0.0.1", "::1"}, repr(row)
        if row["event"] == "socket.bind":
            assert row["address"][1] == 0, repr(row)
        else:
            assert row["listener_target_matches"] is True, repr(row)
    assert sum(r["event"] == "socket.bind" for r in events) == sum(
        r["event"] == "socket.connect" for r in events), "unmatched IPC operations"


def setUpModule():
    global STACK, Base, db_double, settings_double, sqlalchemy, Session, sessionmaker
    global StaticPool, select, FastAPI, TestClient, httpx, client_module, jwt
    global Evidence, EvidenceHistory, EvidenceMedia, AuditLog, User, Role
    global EvidenceDetail, EvidenceHistoryOut, api, dependencies, security
    assert sys.dont_write_bytecode, "BLOCKED: run with -B"
    assert DEPS.is_dir()
    assert not any(n == "app" or n.startswith("app.") for n in sys.modules)
    assert not any(n.split(".")[0] in RISKY for n in sys.modules)
    assert socket.socketpair is socket._fallback_socketpair, "BLOCKED: unreviewed socketpair"
    STACK = ExitStack()
    OBS.update(active=True, restored=False)
    unittest.addModuleCleanup(cleanup_module)
    sys.addaudithook(audit_observer)
    previous_path = sys.path[:]
    STACK.callback(lambda: sys.path.__setitem__(slice(None), previous_path))
    sys.path.extend([str(DEPS), str(BACKEND)])
    original_import = builtins.__import__

    def guarded_import(name, globals=None, locals=None, fromlist=(), level=0):
        check_import(name, fromlist)
        return original_import(name, globals, locals, fromlist, level)

    STACK.enter_context(patch.object(builtins, "__import__", guarded_import))
    STACK.enter_context(patch.object(sys, "meta_path", [ImportFinder(), *sys.meta_path]))

    static_report = []
    for name, relative in APP_SOURCES.items():
        tree = ast.parse((BACKEND / relative).read_bytes(), filename=relative)
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                assert not node.level, "BLOCKED: unreviewed relative import"
                if node.module and node.module.startswith("app"):
                    assert node.module in APP_SOURCES
            elif isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name.startswith("app"):
                        assert alias.name in APP_SOURCES
        if name in {"app", "app.api", "app.core"}:
            assert all(isinstance(n, ast.Expr) and isinstance(n.value, ast.Constant)
                       and isinstance(n.value.value, str) for n in tree.body)
        static_report.append({
            "module": name, "action": "STUB_BEFORE_IMPORT"
            if name in {"app.db", "app.core.settings"} else "REVIEWED_SOURCE",
        })
    print("STEP_A_HTTP_STATIC_IMPORTS " + json.dumps(static_report), flush=True)

    import fastapi
    import starlette
    import pydantic
    import anyio
    import httpx as hx
    import httpcore
    import jwt as jwt_module
    import sqlalchemy as sa
    import starlette.testclient as sc
    from fastapi import FastAPI as App
    from sqlalchemy import create_engine, select as sql_select
    from sqlalchemy.orm import DeclarativeBase, Session as DbSession, sessionmaker as Factory
    from sqlalchemy.pool import StaticPool as MemoryPool
    from asyncio.windows_events import IocpProactor

    FastAPI, TestClient, httpx, client_module = App, sc.TestClient, hx, sc
    sqlalchemy, Session, sessionmaker, StaticPool = sa, DbSession, Factory, MemoryPool
    select, jwt = sql_select, jwt_module
    for module in (fastapi, starlette, pydantic, anyio, sa, hx, httpcore, jwt_module):
        origin = Path(module.__file__).resolve()
        expected = DEPS if module in (hx, httpcore) else SITE
        assert origin.is_relative_to(expected.resolve()), "BLOCKED: wrong import origin"
        OBS["origins"][module.__name__] = str(origin)
    assert hx.__version__ == "0.28.1" and httpcore.__version__ == "1.0.9"
    assert issubclass(sc.TestClient, hx.Client)
    print("STEP_A_HTTP_IMPORT_ORIGINS " + json.dumps(OBS["origins"]), flush=True)

    def refuse_service_connect(*args, **kwargs):
        blocked("IocpProactor.connect_service_path")

    def refuse_http_transport(*args, **kwargs):
        blocked("httpx_real_network_transport")

    async def refuse_async_http_transport(*args, **kwargs):
        blocked("httpx_real_async_network_transport")

    # Unconditional denials for service paths, with no socketpair exception.
    STACK.enter_context(patch.object(IocpProactor, "connect", refuse_service_connect))
    STACK.enter_context(patch.object(hx.HTTPTransport, "handle_request", refuse_http_transport))
    STACK.enter_context(patch.object(hx.AsyncHTTPTransport, "handle_async_request", refuse_async_http_transport))
    original_handle = sc._TestClientTransport.handle_request

    def observe_asgi_request(transport, request):
        assert request.url.host == "testserver"
        OBS["asgi_requests"].append({"method": request.method, "path": request.url.path})
        return original_handle(transport, request)

    STACK.enter_context(patch.object(sc._TestClientTransport, "handle_request", observe_asgi_request))

    def memory_engine(url="sqlite://", **kwargs):
        if str(url) not in {"sqlite://", "sqlite:///:memory:"} or "creator" in kwargs:
            blocked("non_memory_engine")
        OBS["engines"] += 1
        return create_engine(url, **kwargs)

    globals()["memory_engine"] = memory_engine
    STACK.enter_context(patch.object(sa, "create_engine", memory_engine))

    class MemoryBase(DeclarativeBase):
        pass

    Base = MemoryBase

    def forbidden_get_db():
        blocked("production_session_provider")
        yield None

    db_double = types.ModuleType("app.db")
    db_double.Base = Base
    db_double.engine = None
    db_double.SessionLocal = forbidden_get_db
    db_double.get_db = forbidden_get_db
    settings_double = types.ModuleType("app.core.settings")
    settings_double.settings = types.SimpleNamespace(
        app_env="testing", jwt_secret_key=SYNTHETIC_KEY, jwt_expire_minutes=60)
    STACK.callback(remove_app_modules)
    sys.modules["app.db"] = db_double
    sys.modules["app.core.settings"] = settings_double

    from app.api import evidence
    from app import dependencies as deps, audit
    from app.core import security as sec
    from app.models import Evidence as Ev, EvidenceHistory as Hist, EvidenceMedia as Media
    from app.models import AuditLog as Audit, User as Account, Role as AccountRole
    from app.schemas import EvidenceDetail as Detail, EvidenceHistoryOut as HistOut

    api, dependencies, security = evidence, deps, sec
    Evidence, EvidenceHistory, EvidenceMedia, AuditLog = Ev, Hist, Media, Audit
    User, Role, EvidenceDetail, EvidenceHistoryOut = Account, AccountRole, Detail, HistOut
    assert Path(api.__file__).resolve() == (BACKEND / "app/api/evidence.py").resolve()
    assert sys.modules["app.db"] is db_double and not hasattr(db_double, "__file__")
    assert sys.modules["app.core.settings"] is settings_double and not hasattr(settings_double, "__file__")
    assert "app.main" not in sys.modules and "pyodbc" not in sys.modules


def tearDownModule():
    try:
        assert not OBS["blocked"], OBS["blocked"]
        verify_ipc(OBS["socket_events"])
        assert OBS["request_sessions"] == 0
        assert OBS["engines"] == OBS["disposed"]
        assert OBS["clients"] == OBS["closed_clients"]
        assert "pyodbc" not in sys.modules and "app.main" not in sys.modules
        print("STEP_A_HTTP_OBSERVATIONS " + json.dumps({
            "mode": "SYNTHETIC_TEST in-process FastAPI/Starlette HTTP",
            "blocked": OBS["blocked"], "memory_connections": OBS["memory_connections"],
            "engines": OBS["engines"], "disposed": OBS["disposed"],
            "clients": OBS["clients"], "closed_clients": OBS["closed_clients"],
            "request_sessions_active": OBS["request_sessions"],
            "asgi_requests": OBS["asgi_requests"], "socket_events": OBS["socket_events"],
            "auth_override": False, "real_settings_or_db_imported": False,
            "native_network_sandbox_claim": False,
        }), flush=True)
    finally:
        cleanup_module()


class HttpFixture(unittest.TestCase):
    def setUp(self):
        self.engine = memory_engine(
            "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)

        def dispose():
            self.engine.dispose()
            OBS["disposed"] += 1

        self.addCleanup(dispose)
        with self.engine.connect() as connection:
            connection.exec_driver_sql("PRAGMA foreign_keys=ON")
            connection.exec_driver_sql("PRAGMA temp_store=MEMORY")
        Base.metadata.create_all(self.engine)
        self.factory = sessionmaker(bind=self.engine, autoflush=False, expire_on_commit=False)
        with self.factory() as db:
            roles = {name: Role(id=i, name=name)
                     for i, name in enumerate(("admin", "manager", "operator", "viewer"), 1)}
            db.add_all(roles.values())
            for i, name in enumerate(("admin", "manager", "operator", "viewer", "no_role", "inactive"), 1):
                db.add(User(
                    id=i, username="SYNTHETIC_TEST_" + name,
                    email=name + "@example.com", full_name="SYNTHETIC_TEST " + name,
                    password_hash="SYNTHETIC_TEST_NOT_A_REAL_PASSWORD_HASH",
                    is_active=name != "inactive", created_at=FIXED, updated_at=FIXED,
                    roles=[roles[name]] if name in roles else []))
            for i in (1, 2):
                db.add(Evidence(
                    id=i, evidence_code="SYNTHETIC_TEST_" + str(i),
                    event_type="touching", severity="medium", processing_status="pending",
                    source="demo", detected_at=FIXED, created_at=FIXED, updated_at=FIXED))
            db.commit()
        self.app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)
        self.app.include_router(api.router, prefix="/api/v1")

        def request_db():
            OBS["request_sessions"] += 1
            try:
                with self.factory() as db:
                    yield db
            finally:
                OBS["request_sessions"] -= 1

        self.app.dependency_overrides[db_double.get_db] = request_db
        self.addCleanup(self.app.dependency_overrides.clear)
        self.ipc_start = len(OBS["socket_events"])
        self.client = TestClient(self.app, raise_server_exceptions=False)
        self.addCleanup(self.client.close)
        self.client.__enter__()
        OBS["clients"] += 1

        def close_client():
            try:
                self.client.__exit__(None, None, None)
            finally:
                self.client.close()
            OBS["closed_clients"] += 1
            verify_ipc(OBS["socket_events"][self.ipc_start:])

        self.addCleanup(close_client)
        self.assertIsInstance(self.client._transport, client_module._TestClientTransport)
        self.assertEqual(self.client._mounts, {})

    def headers(self, user_id=3):
        return {"Authorization": "Bearer " + security.create_access_token(str(user_id))}

    def get_detail(self, ident=1, headers=None):
        return self.client.get(
            "/api/v1/evidences/" + str(ident),
            headers=self.headers() if headers is None else headers)

    def update(self, status="reviewed", note=NOTE, ident=1, headers=None):
        return self.client.patch(
            "/api/v1/evidences/" + str(ident) + "/status",
            headers=self.headers() if headers is None else headers,
            json={"processing_status": status, "note": note})

    def snapshot(self):
        with self.factory() as db:
            evidence = [(e.id, e.processing_status, e.updated_at)
                        for e in db.scalars(select(Evidence).order_by(Evidence.id))]
            history = [(h.id, h.evidence_id, h.user_id, h.from_status,
                        h.to_status, h.note, h.changed_at)
                       for h in db.scalars(select(EvidenceHistory).order_by(EvidenceHistory.id))]
            audit = [(a.id, a.user_id, a.action, a.entity_type, a.entity_id,
                      a.detail, a.result, a.created_at)
                     for a in db.scalars(select(AuditLog).order_by(AuditLog.id))]
            return evidence, history, audit

    def seed_history(self, evidence_id, when, ident, user_id=3):
        with self.factory() as db:
            db.add(EvidenceHistory(
                id=ident, evidence_id=evidence_id, user_id=user_id,
                from_status="pending", to_status="reviewed",
                note="SYNTHETIC_TEST history", changed_at=when))
            db.commit()

    def assert_denied_without_write(self, response, status, before):
        self.assertEqual(response.status_code, status, response.text)
        self.assertEqual(self.snapshot(), before)

    def assert_rollback(self, owner, attribute, replacement):
        before = self.snapshot()
        calls = []
        original = Session.rollback

        def rollback(db, *args, **kwargs):
            calls.append(True)
            return original(db, *args, **kwargs)

        with patch.object(Session, "rollback", rollback), patch.object(owner, attribute, replacement):
            response = self.update()
        self.assertEqual(response.status_code, 500, response.text)
        self.assertEqual(self.snapshot(), before)
        self.assertGreaterEqual(len(calls), 1)


class HttpIsolationTests(HttpFixture):
    def test_only_db_dependency_is_overridden(self):
        self.assertEqual(set(self.app.dependency_overrides), {db_double.get_db})
        self.assertIs(api.get_current_user, dependencies.get_current_user)
        self.assertIs(inspect.signature(api.get_evidence).parameters["_"].default.dependency,
                      dependencies.get_current_user)
        checker = inspect.signature(api.update_evidence_status).parameters["user"].default.dependency
        self.assertIs(inspect.signature(checker).parameters["user"].default.dependency,
                      dependencies.get_current_user)
        self.assertNotIn("app.main", sys.modules)
        self.assertNotIn("pyodbc", sys.modules)

    def test_memory_database_and_real_fixtures(self):
        self.assertEqual(str(self.engine.url), "sqlite://")
        with self.engine.connect() as connection:
            databases = connection.exec_driver_sql("PRAGMA database_list").all()
            self.assertIn((0, "main", ""), databases)
            self.assertTrue(all(name in {"main", "temp"} and path == ""
                                for _, name, path in databases))
            self.assertEqual(connection.exec_driver_sql("PRAGMA temp_store").scalar(), 2)
        with self.factory() as db:
            self.assertEqual(db.get(User, 3).roles[0].name, "operator")
        self.assertFalse(hasattr(db_double, "__file__"))
        self.assertFalse(hasattr(settings_double, "__file__"))

    def test_actual_asgi_transport_and_successful_authenticated_request(self):
        response = self.get_detail()
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["id"], 1)
        self.assertEqual(self.client._mounts, {})
        verify_ipc(OBS["socket_events"][self.ipc_start:])
        self.assertTrue(OBS["socket_events"][self.ipc_start:])

    def test_real_evidence_routes_bound_to_response_model(self):
        for path, method, endpoint in (
            ("/api/v1/evidences/{evidence_id}", "GET", api.get_evidence),
            ("/api/v1/evidences/{evidence_id}/status", "PATCH", api.update_evidence_status),
        ):
            self.assertEqual(str(self.app.url_path_for(endpoint.__name__, evidence_id=1)),
                             path.replace("{evidence_id}", "1"))
            route = next(r for r in api.router.routes
                         if "/api/v1" + r.path == path and method in r.methods)
            self.assertIs(route.endpoint, endpoint)
            self.assertIs(route.response_model, EvidenceDetail)


class EvidenceHttpTests(HttpFixture):
    def test_get_empty_history_correct_evidence_and_no_write(self):
        before = self.snapshot()
        response = self.get_detail()
        self.assertEqual(response.status_code, 200, response.text)
        body = response.json()
        self.assertEqual(body["evidence_code"], "SYNTHETIC_TEST_1")
        self.assertEqual(body["source"], "demo")
        self.assertEqual(body["history"], [])
        self.assertEqual(self.snapshot(), before)

    def test_get_history_filters_id_and_orders_time_then_id(self):
        self.seed_history(1, FIXED + timedelta(days=2), 10)
        self.seed_history(1, FIXED + timedelta(days=2), 11)
        self.seed_history(1, FIXED + timedelta(days=1), 12)
        self.seed_history(2, FIXED + timedelta(days=8), 99)
        response = self.get_detail()
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual([h["id"] for h in response.json()["history"]], [11, 10, 12])

    def test_get_nullable_user_and_serialized_media(self):
        self.seed_history(1, FIXED, 10, user_id=None)
        with self.factory() as db:
            db.add(EvidenceMedia(
                evidence_id=1, media_type="image", file_path="SYNTHETIC_TEST_NOT_OPENED.jpg",
                file_size=7, mime_type="image/jpeg", created_at=FIXED))
            db.commit()
        response = self.get_detail()
        self.assertEqual(response.status_code, 200, response.text)
        body = response.json()
        self.assertIsNone(body["history"][0]["user_name"])
        self.assertTrue(body["has_image"])
        self.assertFalse(body["has_video"])
        self.assertEqual(body["media"][0]["file_path"], "SYNTHETIC_TEST_NOT_OPENED.jpg")

    def test_get_response_schema_json_and_datetime(self):
        response = self.get_detail()
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.headers["content-type"], "application/json")
        body = response.json()
        self.assertEqual(set(body), set(EvidenceDetail.model_fields))
        self.assertEqual(body["detected_at"], FIXED.isoformat())
        EvidenceDetail.model_validate(body)

    def test_get_missing_evidence_404(self):
        before = self.snapshot()
        self.assert_denied_without_write(self.get_detail(999), 404, before)

    def test_patch_missing_evidence_404(self):
        before = self.snapshot()
        self.assert_denied_without_write(self.update(ident=999), 404, before)

    def test_patch_get_and_persisted_rows_match(self):
        response = self.update()
        self.assertEqual(response.status_code, 200, response.text)
        body = response.json()
        EvidenceDetail.model_validate(body)
        self.assertEqual(body["processing_status"], "reviewed")
        self.assertEqual(body["history"][0]["note"], NOTE)
        self.assertEqual(body["history"][0]["user_name"], "SYNTHETIC_TEST operator")
        later = self.get_detail()
        self.assertEqual(later.status_code, 200, later.text)
        self.assertEqual(later.json(), body)
        evidences, history, audit = self.snapshot()
        self.assertEqual(evidences[0][1], "reviewed")
        self.assertEqual(evidences[0][2].isoformat(), body["updated_at"])
        self.assertEqual(history[0][0], body["history"][0]["id"])
        self.assertEqual(history[0][2:6], (3, "pending", "reviewed", NOTE))
        self.assertEqual(audit[0][1:7], (3, "update_status", "evidence", 1, "reviewed", "success"))

    def test_same_status_each_patch_preserves_note_history_audit_updated_at(self):
        # FastAPI lazily evaluates route annotations, including datetime | None.
        # Build the real route contexts before replacing this module clock.
        before_warmup = self.snapshot()
        warmup = self.get_detail()
        self.assertEqual(warmup.status_code, 200, warmup.text)
        self.assertEqual(self.snapshot(), before_warmup)
        previous = FIXED
        for index, note in enumerate(("  SYNTHETIC_TEST first  ", "SYNTHETIC_TEST second"), 1):
            stamp = FIXED + timedelta(days=index)
            with patch.object(api, "datetime", types.SimpleNamespace(utcnow=lambda: stamp)):
                response = self.update(note=note)
            self.assertEqual(response.status_code, 200, response.text)
            evidences, history, audit = self.snapshot()
            self.assertEqual(len(history), index)
            self.assertEqual(len(audit), index)
            self.assertEqual(evidences[0][2], stamp)
            self.assertGreater(evidences[0][2], previous)
            self.assertEqual(history[-1][5], note)
            self.assertEqual(history[-1][3:5],
                             ("pending" if index == 1 else "reviewed", "reviewed"))
            self.assertEqual(response.json()["history"][0]["note"], note)
            previous = stamp

    def test_same_status_null_note_still_writes(self):
        self.assertEqual(self.update().status_code, 200)
        response = self.update(note=None)
        self.assertEqual(response.status_code, 200, response.text)
        _, history, audit = self.snapshot()
        self.assertEqual(len(history), 2)
        self.assertEqual(len(audit), 2)
        self.assertIsNone(history[-1][5])

    def test_empty_note_preserved(self):
        response = self.update(note="")
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(self.snapshot()[1][0][5], "")

    def test_note_500_characters_preserved(self):
        response = self.update(note="n" * 500)
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(self.snapshot()[1][0][5], "n" * 500)

    def test_missing_required_body_field_422_no_commit(self):
        before = self.snapshot()
        commits = []
        original = Session.commit

        def commit(db, *args, **kwargs):
            commits.append(True)
            return original(db, *args, **kwargs)

        with patch.object(Session, "commit", commit):
            response = self.client.patch(
                "/api/v1/evidences/1/status", headers=self.headers(), json={"note": "SYNTHETIC_TEST"})
        self.assert_denied_without_write(response, 422, before)
        self.assertEqual(commits, [])
        self.assertTrue(any(e["loc"][-1] == "processing_status" for e in response.json()["detail"]))

    def test_invalid_status_422_no_write(self):
        before = self.snapshot()
        self.assert_denied_without_write(self.update(status="pending"), 422, before)

    def test_numeric_status_422_no_write(self):
        before = self.snapshot()
        self.assert_denied_without_write(self.update(status=123), 422, before)

    def test_null_status_422_no_write(self):
        before = self.snapshot()
        self.assert_denied_without_write(self.update(status=None), 422, before)

    def test_numeric_note_422_no_write(self):
        before = self.snapshot()
        self.assert_denied_without_write(self.update(note=123), 422, before)

    def test_note_501_characters_422_no_write(self):
        before = self.snapshot()
        self.assert_denied_without_write(self.update(note="n" * 501), 422, before)

    def test_malformed_json_422_no_write(self):
        before = self.snapshot()
        headers = {**self.headers(), "Content-Type": "application/json"}
        response = self.client.patch(
            "/api/v1/evidences/1/status", headers=headers, content="{SYNTHETIC_TEST")
        self.assert_denied_without_write(response, 422, before)

    def test_invalid_path_parameter_422_no_write(self):
        before = self.snapshot()
        self.assert_denied_without_write(self.get_detail("not_an_integer"), 422, before)

    def test_success_commits_once(self):
        calls = []
        original = Session.commit

        def commit(db, *args, **kwargs):
            calls.append(True)
            return original(db, *args, **kwargs)

        with patch.object(Session, "commit", commit):
            response = self.update()
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(len(calls), 1)
        self.assertEqual(len(self.snapshot()[1]), 1)

    def test_detail_construction_error_500_rolls_back(self):
        def fail(*args, **kwargs):
            raise RuntimeError("SYNTHETIC_TEST detail construction")
        self.assert_rollback(api, "_evidence_detail", fail)

    def test_real_response_model_validation_error_500_rolls_back(self):
        original = EvidenceHistoryOut

        def invalid(**values):
            values["id"] = "SYNTHETIC_TEST_NOT_INTEGER"
            return original(**values)
        self.assert_rollback(api, "EvidenceHistoryOut", invalid)

    def test_flush_error_500_rolls_back(self):
        def fail(*args, **kwargs):
            raise RuntimeError("SYNTHETIC_TEST flush")
        self.assert_rollback(Session, "flush", fail)

    def test_commit_error_before_durable_commit_500_rolls_back(self):
        def fail(*args, **kwargs):
            raise RuntimeError("SYNTHETIC_TEST precommit")
        self.assert_rollback(Session, "commit", fail)

    def test_refresh_error_500_rolls_back(self):
        def fail(*args, **kwargs):
            raise RuntimeError("SYNTHETIC_TEST refresh")
        self.assert_rollback(Session, "refresh", fail)

    def test_history_select_error_500_rolls_back(self):
        original = Session.scalars

        def fail(db, statement, *args, **kwargs):
            if any(c.get("entity") is EvidenceHistory for c in statement.column_descriptions):
                raise RuntimeError("SYNTHETIC_TEST history select")
            return original(db, statement, *args, **kwargs)
        self.assert_rollback(Session, "scalars", fail)

    def test_audit_error_500_rolls_back(self):
        def fail(*args, **kwargs):
            raise RuntimeError("SYNTHETIC_TEST audit")
        self.assert_rollback(api, "record_audit", fail)


class AuthHttpTests(HttpFixture):
    def assert_auth_denied(self, response, status, before):
        self.assert_denied_without_write(response, status, before)
        if status == 401:
            self.assertEqual(response.headers.get("www-authenticate"), "Bearer")

    def test_missing_credentials_get_401(self):
        before = self.snapshot()
        self.assert_auth_denied(self.get_detail(headers={}), 401, before)

    def test_missing_credentials_patch_401(self):
        before = self.snapshot()
        self.assert_auth_denied(self.update(headers={}), 401, before)

    def test_basic_scheme_401(self):
        before = self.snapshot()
        self.assert_auth_denied(
            self.update(headers={"Authorization": "Basic SYNTHETIC_TEST"}), 401, before)

    def test_malformed_bearer_token_401(self):
        before = self.snapshot()
        self.assert_auth_denied(
            self.update(headers={"Authorization": "Bearer SYNTHETIC_TEST.invalid"}), 401, before)

    def test_wrong_signature_401(self):
        token = jwt.encode(
            {"sub": "3", "exp": datetime.now(timezone.utc) + timedelta(minutes=5)},
            "SYNTHETIC_TEST_WRONG_SIGNATURE_KEY_32_PLUS_BYTES", algorithm=security.ALGORITHM)
        before = self.snapshot()
        self.assert_auth_denied(
            self.update(headers={"Authorization": "Bearer " + token}), 401, before)

    def test_expired_token_401(self):
        token = jwt.encode(
            {"sub": "3", "exp": datetime.now(timezone.utc) - timedelta(minutes=5)},
            SYNTHETIC_KEY, algorithm=security.ALGORITHM)
        before = self.snapshot()
        self.assert_auth_denied(
            self.update(headers={"Authorization": "Bearer " + token}), 401, before)

    def test_noninteger_subject_401(self):
        token = security.create_access_token("SYNTHETIC_TEST_NOT_INTEGER")
        before = self.snapshot()
        self.assert_auth_denied(
            self.update(headers={"Authorization": "Bearer " + token}), 401, before)

    def test_unknown_user_401(self):
        before = self.snapshot()
        self.assert_auth_denied(self.update(headers=self.headers(999)), 401, before)

    def test_inactive_user_401(self):
        before = self.snapshot()
        self.assert_auth_denied(self.update(headers=self.headers(6)), 401, before)

    def test_viewer_can_get_200(self):
        response = self.get_detail(headers=self.headers(4))
        self.assertEqual(response.status_code, 200, response.text)

    def test_viewer_cannot_patch_403(self):
        before = self.snapshot()
        self.assert_auth_denied(self.update(headers=self.headers(4)), 403, before)

    def test_user_without_roles_cannot_patch_403(self):
        before = self.snapshot()
        self.assert_auth_denied(self.update(headers=self.headers(5)), 403, before)

    def test_user_without_roles_can_get_200(self):
        response = self.get_detail(headers=self.headers(5))
        self.assertEqual(response.status_code, 200, response.text)

    def test_all_actual_writer_roles_can_patch_200(self):
        for ident in (1, 2, 3):
            with self.subTest(user_id=ident):
                response = self.update(headers=self.headers(ident))
                self.assertEqual(response.status_code, 200, response.text)
        _, history, audit = self.snapshot()
        self.assertEqual([row[2] for row in history], [1, 2, 3])
        self.assertEqual([row[1] for row in audit], [1, 2, 3])


if __name__ == "__main__":
    unittest.main(verbosity=2)
