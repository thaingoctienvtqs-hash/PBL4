"""Explicit, fail-closed configuration for the isolated integration application."""
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
import hashlib
import json
import os
import re
from uuid import UUID

PROFILE = "ARTGUARD_INTEGRATION_TEST"
EXPECTED_DATABASE = "ArtGuard_Integration_TEST"
EXPECTED_SERVER = r"DESKTOP-2K5T32D\SQLEXPRESS"
EXPECTED_USER = "artguard_integration_app"
_ALLOWED_ORIGINS = {"SYNTHETIC_TEST", "REAL_AI"}

@dataclass(frozen=True)
class Producer:
    producer_id: str
    token_sha256: str = field(repr=False)
    allowed_origins: tuple[str, ...] = ()
    producer_instance_id: str | None = None
    artwork_id: int | None = None
    device_id: int | None = None

@dataclass(frozen=True)
class IntegrationConfig:
    profile: str
    database: dict[str, Any]
    media_root: Path
    artwork_root: Path
    jwt_secret_key: str = field(repr=False)
    producers: tuple[Producer, ...] = ()
    jwt_expire_minutes: int = 60
    cors_origins: tuple[str, ...] = ()

def load_config(path: str | Path | None = None) -> IntegrationConfig:
    selected = path or os.environ.get("ARTGUARD_INTEGRATION_CONFIG")
    if not selected:
        raise RuntimeError("Explicit ARTGUARD_INTEGRATION_CONFIG is required; no fallback")
    config_path = Path(selected).expanduser().resolve()
    if not config_path.is_file() or config_path.stat().st_size > 65536:
        raise RuntimeError("Integration config is missing or exceeds 64KiB")
    raw = json.loads(config_path.read_text(encoding="utf-8"))
    allowed = {"profile", "database", "media_root", "artwork_root", "jwt_secret_key",
               "jwt_expire_minutes", "cors_origins", "producers"}
    if set(raw) - allowed or raw.get("profile") != PROFILE:
        raise ValueError("Invalid integration profile or unknown configuration fields")
    database = dict(raw["database"])
    allowed_db = {"kind", "server", "port", "driver", "name", "expected_server",
                  "database_user", "trusted_connection", "encrypt", "trust_server_certificate"}
    if set(database) - allowed_db:
        raise ValueError("Unknown database configuration fields")
    if (database.get("kind") != "mssql"
        or database.get("name") != EXPECTED_DATABASE
        or database.get("expected_server", "").casefold() != EXPECTED_SERVER.casefold()
        or database.get("database_user") != EXPECTED_USER
        or database.get("server") != "127.0.0.1"
        or database.get("port") != 56929
        or database.get("trusted_connection") is not True
        or database.get("encrypt") is not True):
        raise ValueError("Unapproved database target or authentication profile")
    project = Path(__file__).resolve().parents[4]
    roots = []
    for key in ("media_root", "artwork_root"):
        value = Path(raw[key]).expanduser()
        if not value.is_absolute():
            raise ValueError("Media roots must be absolute")
        value = value.resolve()
        if value == project or value.is_relative_to(project):
            raise ValueError("Integration media cannot be written into the repository")
        roots.append(value)
    secret = raw.get("jwt_secret_key", "")
    if not isinstance(secret, str) or len(secret) < 32:
        raise ValueError("A separate integration JWT key of at least 32 characters is required")
    producers = []
    identities = set()
    for item in raw.get("producers", []):
        if set(item) - {"producer_id", "token_sha256", "allowed_origins",
                        "producer_instance_id", "artwork_id", "device_id"}:
            raise ValueError("Unknown producer configuration fields")
        ident = item["producer_id"]
        if not re.fullmatch(r"[a-z0-9][a-z0-9_-]{0,79}", ident) or ident in identities:
            raise ValueError("Invalid or duplicate producer identity")
        identities.add(ident)
        token_hash = item["token_sha256"]
        if not re.fullmatch(r"[0-9a-f]{64}", token_hash):
            raise ValueError("Producer credential must be a SHA-256 digest")
        origins = tuple(item.get("allowed_origins", []))
        if not origins or not set(origins) <= _ALLOWED_ORIGINS:
            raise ValueError("Producer origin scope is required")
        instance = item.get("producer_instance_id")
        if instance is not None:
            instance = str(UUID(instance))
        for key in ("artwork_id", "device_id"):
            value = item.get(key)
            if value is not None and (type(value) is not int or value <= 0):
                raise ValueError("Producer mapping identifiers must be positive integers")
        producers.append(Producer(ident, token_hash, origins, instance,
                                  item.get("artwork_id"), item.get("device_id")))
    if not producers:
        raise ValueError("At least one integration producer must be configured")
    minutes = raw.get("jwt_expire_minutes", 60)
    if type(minutes) is not int or not 1 <= minutes <= 1440:
        raise ValueError("Invalid JWT expiration")
    return IntegrationConfig(PROFILE, database, roots[0], roots[1], secret,
                             tuple(producers), minutes, tuple(raw.get("cors_origins", [])))

def build_test_engine(config: IntegrationConfig):
    from sqlalchemy import create_engine, event
    from sqlalchemy.engine import URL
    db = config.database
    if config.profile != PROFILE or db.get("name") != EXPECTED_DATABASE:
        raise RuntimeError("Integration database guard rejected target")
    url = URL.create("mssql+pyodbc", host=db["server"], port=db["port"],
                     database=db["name"], query={
                         "driver": db["driver"], "Trusted_Connection": "yes",
                         "Encrypt": "yes", "TrustServerCertificate":
                         "yes" if db.get("trust_server_certificate") else "no"})
    engine = create_engine(url, pool_pre_ping=True, pool_recycle=1800)

    def restrict(dbapi_connection):
        cursor = dbapi_connection.cursor()
        try:
            row = cursor.execute(
                "SELECT CONVERT(nvarchar(128), SERVERPROPERTY('ServerName')), DB_NAME(), USER_NAME()"
            ).fetchone()
            if not row or str(row[0]).casefold() != EXPECTED_SERVER.casefold() or row[1] != EXPECTED_DATABASE:
                raise RuntimeError("SQL Server/database identity mismatch")
            if row[2] != EXPECTED_USER:
                cursor.execute("EXECUTE AS USER = N'artguard_integration_app'")
            row = cursor.execute(
                "SELECT DB_NAME(), USER_NAME(), IS_ROLEMEMBER('db_owner'), "
                "HAS_PERMS_BY_NAME(DB_NAME(), 'DATABASE', 'CREATE TABLE')"
            ).fetchone()
            if not row or row[0] != EXPECTED_DATABASE or row[1] != EXPECTED_USER or row[2] != 0 or row[3] != 0:
                raise RuntimeError("Integration connection is not restricted to the approved DML user")
        finally:
            cursor.close()

    @event.listens_for(engine, "connect")
    def on_connect(connection, record):
        restrict(connection)

    @event.listens_for(engine, "checkout")
    def on_checkout(connection, record, proxy):
        restrict(connection)
    return engine
