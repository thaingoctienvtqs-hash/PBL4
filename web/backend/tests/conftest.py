import os

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

# API tests deliberately use an isolated SQLite engine; runtime defaults remain SQL Server.
os.environ["APP_ENV"] = "testing"

from app.db import Base, get_db
from app.main import app
from app.models import Role, User
from app.core.security import hash_password


@pytest.fixture()
def database():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    db = factory()
    roles = {name: Role(name=name) for name in ("admin", "manager", "operator")}
    db.add_all(roles.values())
    db.flush()
    for name, role in roles.items():
        db.add(User(username=name, email=f"{name}@example.com", full_name=f"{name.title()} Demo", password_hash=hash_password("TestPassword2026!"), roles=[role]))
    db.commit()
    db.close()

    def override_get_db():
        session = factory()
        try:
            yield session
        finally:
            session.close()

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as client:
        yield client, factory
    app.dependency_overrides.clear()
    engine.dispose()
