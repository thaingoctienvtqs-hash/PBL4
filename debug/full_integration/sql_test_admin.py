"""Approved integration TEST administration only; never a production migration runner."""
import argparse
import json
import re
import sys
import types
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
BACKEND = ROOT / "web" / "backend"
EXPECTED_SERVER = "DESKTOP-2K5T32D\\SQLEXPRESS"
EXPECTED_DATABASE = "ArtGuard_Integration_TEST"
EXPECTED_USER = "artguard_integration_app"


def write_new_json(path, data):
    with Path(path).open("x", encoding="utf8") as handle:
        json.dump(data, handle, indent=2, default=str)


def load_approved(run):
    run = Path(run).resolve()
    approval = json.loads((run / "sql_approval.json").read_text(encoding="utf8"))
    config = json.loads((run / "integration_config.json").read_text(encoding="utf8"))
    if (approval.get("server") != EXPECTED_SERVER
            or approval.get("database") != EXPECTED_DATABASE
            or approval.get("database_user") != EXPECTED_USER
            or approval.get("allow_create_schema_seed") is not True):
        raise RuntimeError("Explicit approved TEST identity is required")
    db = config["database"]
    if (db.get("name") != EXPECTED_DATABASE
            or db.get("expected_server") != EXPECTED_SERVER
            or db.get("server") != "127.0.0.1"
            or db.get("port") != 56929
            or db.get("trusted_connection") is not True):
        raise RuntimeError("TEST configuration does not match approved target")
    return run, approval, config


def admin_engine(config):
    from sqlalchemy import create_engine
    from sqlalchemy.engine import URL
    db = config["database"]
    url = URL.create("mssql+pyodbc", host=db["server"], port=db["port"],
                     database=EXPECTED_DATABASE, query={
                         "driver": db["driver"], "Trusted_Connection": "yes",
                         "Encrypt": "yes", "TrustServerCertificate": "yes"})
    return create_engine(url, connect_args={"timeout": 5}, pool_pre_ping=True)


def verify_identity(connection):
    from sqlalchemy import text
    row = connection.execute(text(
        "SELECT CONVERT(nvarchar(128),SERVERPROPERTY('ServerName')) AS server_name,"
        "DB_NAME() AS database_name,ORIGINAL_LOGIN() AS original_login,"
        "USER_NAME() AS database_user")).mappings().one()
    if (row["server_name"].casefold() != EXPECTED_SERVER.casefold()
            or row["database_name"] != EXPECTED_DATABASE):
        raise RuntimeError("STOP: database identity mismatch")
    return dict(row)


def verify_owned_database(connection, run):
    from sqlalchemy import text
    created = json.loads((run / "logs" / "sql_create_database.json").read_text(encoding="utf8"))
    expected = created["database_identity"]
    row = connection.execute(text(
        "SELECT name,database_id,create_date FROM sys.databases WHERE name=:name"),
        {"name": EXPECTED_DATABASE}).mappings().one()
    if (row["database_id"] != expected["database_id"]
            or str(row["create_date"]) != expected["create_date"]):
        raise RuntimeError("STOP: TEST database was replaced since approval")


def load_registry(engine, config):
    if str(BACKEND) not in sys.path:
        sys.path.append(str(BACKEND))
    from sqlalchemy.orm import DeclarativeBase, sessionmaker
    from app.integration_app import install_test_modules, load_models

    class AdminTestBase(DeclarativeBase):
        pass

    factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    settings = types.SimpleNamespace(
        app_env="integration_test", jwt_secret_key=config["jwt_secret_key"],
        jwt_expire_minutes=config["jwt_expire_minutes"], cors_origins=config["cors_origins"])
    install_test_modules(AdminTestBase, factory, settings, engine)
    models, ai_models = load_models()
    return AdminTestBase, factory, models, ai_models


def apply_approved_migrations(engine, run, base):
    from alembic.config import Config
    from alembic.script import ScriptDirectory
    from alembic.runtime.migration import MigrationContext
    from alembic.operations import Operations
    from sqlalchemy import inspect
    cfg = Config()
    cfg.set_main_option("script_location", str(BACKEND / "migrations"))
    scripts = ScriptDirectory.from_config(cfg)
    revisions = list(reversed(list(scripts.walk_revisions())))
    allowed = {"0001_initial_schema", "0002_add_stream_url_and_evidence",
               "0003_ai_event_receipts"}
    if {r.revision for r in revisions} != allowed:
        raise RuntimeError("Unreviewed migration revision found")
    applied = []
    with engine.begin() as connection:
        verify_identity(connection)
        verify_owned_database(connection, run)
        context = MigrationContext.configure(connection)
        with Operations.context(context):
            for revision in revisions:
                revision.module.upgrade()
                applied.append(revision.revision)
        context.stamp(scripts, "head")
        inspector = inspect(connection)
        missing = set(base.metadata.tables) - set(inspector.get_table_names())
        if missing:
            raise RuntimeError("Missing TEST tables after migration: " + repr(sorted(missing)))
        uniques = [u for u in inspector.get_indexes("ai_event_receipts") if u.get("unique")]
        if not any(set(u["column_names"]) == {"producer_id", "event_id"} for u in uniques):
            raise RuntimeError("Receipt unique constraint was not created")
        schema = {name: {"columns": [c["name"] for c in inspector.get_columns(name)],
                         "unique_indexes": [u for u in inspector.get_indexes(name) if u.get("unique")],
                         "foreign_keys": inspector.get_foreign_keys(name)}
                  for name in ("ai_event_receipts", "ai_event_attachments")}
    return {"applied_or_verified_revisions": applied, "schema": schema}


def grant_app_dml(engine, run, base):
    from sqlalchemy import text
    with engine.begin() as connection:
        verify_identity(connection)
        verify_owned_database(connection, run)
        for table in base.metadata.sorted_tables:
            if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", table.name):
                raise RuntimeError("Unsafe table identifier")
            permissions = "SELECT, INSERT, UPDATE"
            if table.name not in {"ai_event_receipts", "ai_event_attachments", "audit_logs"}:
                permissions += ", DELETE"
            connection.exec_driver_sql(
                "GRANT " + permissions + " ON OBJECT::[dbo].[" + table.name
                + "] TO [artguard_integration_app]")
        connection.exec_driver_sql("EXECUTE AS USER = 'artguard_integration_app'")
        try:
            row = connection.execute(text(
                "SELECT DB_NAME() AS database_name,USER_NAME() AS database_user,"
                "HAS_PERMS_BY_NAME(DB_NAME(),'DATABASE','CREATE TABLE') AS can_create_table,"
                "HAS_PERMS_BY_NAME(DB_NAME(),'DATABASE','CONTROL') AS can_control_database,"
                "IS_MEMBER('db_owner') AS is_db_owner")).mappings().one()
            if (row["database_name"] != EXPECTED_DATABASE
                    or row["database_user"] != EXPECTED_USER
                    or row["can_create_table"] != 0
                    or row["can_control_database"] != 0
                    or row["is_db_owner"] != 0):
                raise RuntimeError("Restricted TEST user permissions are not safe")
            permissions = dict(row)
        finally:
            connection.exec_driver_sql("REVERT")
    return permissions


def seed_approved(engine, run, config, factory, models):
    from sqlalchemy import select
    from app.core.security import hash_password
    private = json.loads((run / "private_test_credentials.json").read_text(encoding="utf8"))
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    ids = {}
    with factory() as session:
        verify_identity(session.connection())
        for name in ("admin", "manager", "operator", "viewer"):
            role = session.scalar(select(models.Role).where(models.Role.name == name))
            if role is None:
                session.add(models.Role(name=name))
        session.flush()
        roles = {r.name: r for r in session.scalars(select(models.Role))}
        for user_config in private["users"]:
            user = session.scalar(select(models.User).where(
                models.User.username == user_config["username"]))
            if user is None:
                user = models.User(
                    username=user_config["username"],
                    email=user_config["username"] + "@example.com",
                    full_name="Integration TEST " + user_config["username"],
                    password_hash=hash_password(user_config["password"]),
                    is_active=True, created_at=now, updated_at=now)
                user.roles = [roles[n] for n in user_config["roles"]]
                session.add(user)
        location = session.scalar(select(models.Location).where(
            models.Location.code == "INTEGRATION_TEST_ROOM"))
        if location is None:
            location = models.Location(code="INTEGRATION_TEST_ROOM",
                                       name="Integration TEST only", is_active=True)
            session.add(location)
        session.flush()
        artwork = session.scalar(select(models.Artwork).where(
            models.Artwork.inventory_code == "MONALISA_INTEGRATION_TEST"))
        if artwork is None:
            artwork = models.Artwork(
                inventory_code="MONALISA_INTEGRATION_TEST", title="Mona Lisa - TEST print",
                artist="Test reproduction", status="displayed", location_id=location.id)
            session.add(artwork)
        session.flush()
        device = session.scalar(select(models.Device).where(
            models.Device.device_code == "ESP32_INTEGRATION_TEST"))
        if device is None:
            device = models.Device(
                device_code="ESP32_INTEGRATION_TEST", name="ESP32-CAM TEST only",
                device_type="esp32_camera", status="offline",
                location_id=location.id, artwork_id=artwork.id,
                notes="Physical camera not yet ready. No stream consumer started.",
                stream_url=None, stream_type=None)
            session.add(device)
        session.flush()
        ids = {"location_id": location.id, "artwork_id": artwork.id, "device_id": device.id}
        session.commit()
    for producer in config["producers"]:
        producer["artwork_id"] = ids["artwork_id"]
        producer["device_id"] = ids["device_id"]
    # This is the new session TEST config, never a repository/production config.
    config_path = run / "integration_config.json"
    revision = run / ("integration_config.before_mapping_" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ") + ".json")
    with revision.open("xb") as handle:
        handle.write(config_path.read_bytes())
    config_path.write_text(json.dumps(config, indent=2), encoding="utf8")
    return ids


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-root", required=True)
    parser.add_argument("--action", choices=("inspect", "bootstrap"), default="inspect")
    args = parser.parse_args()
    run, approval, config = load_approved(args.run_root)
    engine = admin_engine(config)
    report = {"action": args.action, "database": EXPECTED_DATABASE,
              "production_database_writes": False}
    try:
        with engine.connect() as connection:
            report["identity"] = verify_identity(connection)
            verify_owned_database(connection, run)
        if args.action == "bootstrap":
            base, factory, models, ai_models = load_registry(engine, config)
            report["migration"] = apply_approved_migrations(engine, run, base)
            report["restricted_user"] = grant_app_dml(engine, run, base)
            report["mapping"] = seed_approved(engine, run, config, factory, models)
            report["status"] = "TEST_SCHEMA_AND_SEED_READY"
        else:
            report["status"] = "READ_ONLY_IDENTITY_PASS"
    finally:
        engine.dispose()
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    path = run / "logs" / ("sql_admin_" + args.action + "_" + stamp + ".json")
    write_new_json(path, report)
    print(json.dumps({"status": report["status"], "database": EXPECTED_DATABASE,
                      "report": str(path), "mapping": report.get("mapping")}, default=str))


if __name__ == "__main__":
    main()
