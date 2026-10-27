"""Dedicated, explicit TEST application. Importing this module never connects."""
from contextlib import asynccontextmanager
from pathlib import Path
import importlib
import sys
import types
from sqlalchemy.orm import DeclarativeBase, sessionmaker
from app.core.ai_ingest_config import (
    EXPECTED_DATABASE, EXPECTED_USER, PROFILE, IntegrationConfig, build_test_engine, load_config)

def install_test_modules(base, session_factory, settings, engine=None):
    """Install explicit DB/settings providers before any application router import.

    Intended for one dedicated TEST process, including an approved admin schema
    bootstrap process. This function itself performs no database operation.
    """
    if any(name in sys.modules for name in ("app.db", "app.core.settings", "app.models", "app.main")):
        raise RuntimeError("TEST provider installation refused: application modules already loaded")
    db = types.ModuleType("app.db")
    db.Base, db.engine, db.SessionLocal = base, engine, session_factory

    def get_db():
        if db.SessionLocal is None:
            raise RuntimeError("No TEST session factory supplied")
        with db.SessionLocal() as session:
            yield session

    db.get_db = get_db
    config = types.ModuleType("app.core.settings")
    config.settings = settings
    sys.modules["app.db"] = db
    sys.modules["app.core.settings"] = config
    return db, config

def load_models():
    """Register existing and integration metadata, without engine/DDL/DML."""
    return (importlib.import_module("app.models"),
            importlib.import_module("app.ai_event_models"))

def create_app(config_path=None, *, config: IntegrationConfig | None = None, test_engine=None):
    config = config or load_config(config_path)
    if config.profile != PROFILE:
        raise RuntimeError("TEST profile required")
    existing_modules = set(sys.modules)
    if test_engine is None:
        if config.database.get("kind") != "mssql":
            raise RuntimeError("No SQLite or production fallback is allowed")
        engine = build_test_engine(config)
    else:
        if config.database.get("kind") != "sqlite" or str(test_engine.url) not in {"sqlite://", "sqlite:///:memory:"}:
            raise RuntimeError("Injected test engine must be SQLite :memory:")
        engine = test_engine

    class IntegrationBase(DeclarativeBase):
        pass

    factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    settings = types.SimpleNamespace(
        app_env="integration_test", jwt_secret_key=config.jwt_secret_key,
        jwt_expire_minutes=config.jwt_expire_minutes, cors_origins=list(config.cors_origins))
    install_test_modules(IntegrationBase, factory, settings, engine)
    load_models()
    from fastapi import FastAPI
    from fastapi.middleware.cors import CORSMiddleware
    from fastapi.staticfiles import StaticFiles
    from sqlalchemy import text
    from app.api import admin, alerts, auth, dashboard, evidence, resources, ai_events
    from app import artwork_images

    old_evidence_root = evidence.EVIDENCE_UPLOAD_DIR
    old_artwork_root = artwork_images.ARTWORK_UPLOAD_DIR
    evidence.EVIDENCE_UPLOAD_DIR = config.media_root
    artwork_images.ARTWORK_UPLOAD_DIR = config.artwork_root
    config.media_root.mkdir(parents=True, exist_ok=True)
    config.artwork_root.mkdir(parents=True, exist_ok=True)

    @asynccontextmanager
    async def lifespan(app):
        try:
            with engine.connect() as connection:
                connection.execute(text("SELECT 1"))
                if config.database["kind"] == "mssql":
                    identity = connection.execute(text("SELECT DB_NAME(), USER_NAME()")).one()
                    if identity[0] != EXPECTED_DATABASE or identity[1] != EXPECTED_USER:
                        raise RuntimeError("Startup TEST identity verification failed")
            yield
        finally:
            engine.dispose()
            evidence.EVIDENCE_UPLOAD_DIR = old_evidence_root
            artwork_images.ARTWORK_UPLOAD_DIR = old_artwork_root
            # Remove only modules added by this dedicated TEST factory.
            for name in sorted(set(sys.modules) - existing_modules, reverse=True):
                if name == "app" or name.startswith("app."):
                    module = sys.modules.pop(name, None)
                    parent_name, _, child = name.rpartition(".")
                    parent = sys.modules.get(parent_name)
                    if parent is not None and getattr(parent, child, None) is module:
                        delattr(parent, child)

    app = FastAPI(title="ArtGuard isolated integration TEST", version="1.0-test", lifespan=lifespan)
    app.state.integration_config = config
    app.state.integration_engine = engine
    app.state.integration_session_factory = factory
    app.state.integration_base = IntegrationBase
    app.add_middleware(
        CORSMiddleware, allow_origins=list(config.cors_origins), allow_credentials=False,
        allow_methods=["GET", "POST", "PATCH", "PUT", "DELETE", "OPTIONS"],
        allow_headers=["Authorization", "Content-Type", "X-ArtGuard-Producer-Key", "X-Evidence-SHA256"])
    for module in (auth, resources, alerts, dashboard, admin, evidence, ai_events):
        app.include_router(module.router, prefix="/api/v1")
    app.include_router(artwork_images.router, prefix="/api/v1")
    app.mount("/uploads/artworks", StaticFiles(directory=str(config.artwork_root)), name="test-artwork-uploads")

    @app.get("/health")
    def health():
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))
        return {"status": "ok", "profile": PROFILE,
                "database": EXPECTED_DATABASE if config.database["kind"] == "mssql" else ":memory:",
                "mode": "integration_test"}
    return app
