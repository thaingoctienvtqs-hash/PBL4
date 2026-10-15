import os
from io import BytesIO
from uuid import uuid4

import pytest
from PIL import Image
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from app.core.settings import settings
from app.db import get_db
from app.main import app
from seed_demo import DEMO_USERS


pytestmark = pytest.mark.skipif(
    os.getenv("RUN_SQLSERVER_INTEGRATION") != "1",
    reason="Set RUN_SQLSERVER_INTEGRATION=1 after configuring SQL Server access",
)


def test_sql_server_login_crud_dashboard_and_report():
    assert settings.database_url.drivername == "mssql+pyodbc"
    assert settings.db_name.casefold() == "pbl4_art_guard"

    engine = create_engine(settings.database_url, pool_pre_ping=True)
    factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)

    with engine.connect() as connection:
        server_name, database_name, version = connection.execute(
            text("SELECT @@SERVERNAME, DB_NAME(), @@VERSION")
        ).one()
    assert server_name
    assert database_name.casefold() == settings.db_name.casefold()
    assert "Microsoft SQL Server" in version

    def get_sql_server_db():
        session = factory()
        try:
            assert session.execute(text("SELECT DB_NAME()")).scalar_one().casefold() == settings.db_name.casefold()
            yield session
        finally:
            session.close()

    app.dependency_overrides[get_db] = get_sql_server_db
    client = TestClient(app)
    created = {"location": None, "artwork": None, "device": None, "alert": None}
    manager_headers = None
    admin_headers = None
    suffix = uuid4().hex[:12].upper()
    location_code = f"IT-{suffix}"
    artwork_code = f"IT-{suffix}"
    device_code = f"IT-{suffix}"
    alert_title = f"SQL integration {suffix}"

    def login(user_index):
        username, _, _, password, _ = DEMO_USERS[user_index]
        response = client.post("/api/v1/auth/login", json={"username": username, "password": password})
        assert response.status_code == 200, response.text
        return {"Authorization": f"Bearer {response.json()['access_token']}"}

    try:
        manager_headers = login(1)
        admin_headers = login(0)

        location_response = client.post(
            "/api/v1/locations",
            headers=manager_headers,
            json={"code": location_code, "name": f"SQL Test Area {suffix}", "description": "Temporary SQL Server integration record", "capacity": 1},
        )
        assert location_response.status_code == 201, location_response.text
        created["location"] = location_response.json()["id"]
        location_id = created["location"]
        assert client.get(f"/api/v1/locations/{location_id}", headers=manager_headers).json()["code"] == location_code
        updated_location = client.patch(
            f"/api/v1/locations/{location_id}", headers=manager_headers, json={"name": f"SQL Test Area Updated {suffix}"}
        )
        assert updated_location.status_code == 200, updated_location.text
        assert updated_location.json()["name"].endswith(suffix)

        artwork_response = client.post(
            "/api/v1/artworks",
            headers=manager_headers,
            json={"inventory_code": artwork_code, "title": f"SQL Test Artwork {suffix}", "artist": "Integration Test", "location_id": location_id},
        )
        assert artwork_response.status_code == 201, artwork_response.text
        created["artwork"] = artwork_response.json()["id"]
        artwork_id = created["artwork"]
        assert client.get(f"/api/v1/artworks/{artwork_id}", headers=manager_headers).json()["inventory_code"] == artwork_code
        updated_artwork = client.patch(
            f"/api/v1/artworks/{artwork_id}", headers=manager_headers, json={"status": "under_review"}
        )
        assert updated_artwork.status_code == 200, updated_artwork.text
        assert updated_artwork.json()["status"] == "under_review"
        assert client.get("/api/v1/artworks", headers=manager_headers, params={"q": artwork_code}).json()["total"] == 1

        device_response = client.post(
            "/api/v1/devices",
            headers=manager_headers,
            json={"device_code": device_code, "name": f"SQL Test Camera {suffix}", "location_id": location_id, "artwork_id": artwork_id},
        )
        assert device_response.status_code == 201, device_response.text
        created["device"] = device_response.json()["id"]
        device_id = created["device"]
        assert client.get("/api/v1/devices", headers=manager_headers, params={"q": device_code}).json()["total"] == 1
        updated_device = client.patch(f"/api/v1/devices/{device_id}", headers=manager_headers, json={"status": "offline"})
        assert updated_device.status_code == 200, updated_device.text
        assert updated_device.json()["status"] == "offline"
        assert client.get(f"/api/v1/devices/{device_id}/history", headers=manager_headers).status_code == 200

        alert_response = client.post(
            "/api/v1/alerts",
            headers=manager_headers,
            json={"title": alert_title, "description": "Temporary SQL Server integration event", "severity": "high", "artwork_id": artwork_id, "device_id": device_id},
        )
        assert alert_response.status_code == 201, alert_response.text
        created["alert"] = alert_response.json()["id"]
        alert_id = created["alert"]
        assert client.get("/api/v1/alerts", headers=manager_headers, params={"q": alert_title}).json()["total"] == 1
        updated_alert = client.patch(
            f"/api/v1/alerts/{alert_id}/status", headers=manager_headers, json={"status": "investigating", "note": "SQL Server integration check"}
        )
        assert updated_alert.status_code == 200, updated_alert.text
        assert updated_alert.json()["status"] == "investigating"
        assert client.get(f"/api/v1/alerts/{alert_id}/history", headers=manager_headers).status_code == 200

        dashboard = client.get("/api/v1/dashboard", headers=manager_headers, params={"days": 7})
        report = client.get("/api/v1/reports/summary", headers=manager_headers, params={"days": 7})
        assert dashboard.status_code == 200, dashboard.text
        assert report.status_code == 200, report.text
        assert any(item["id"] == alert_id for item in dashboard.json()["recent_alerts"])
        assert report.json()["period_days"] == 7

        # Verify a committed write can be read through a fresh SQL Server connection.
        with engine.connect() as connection:
            persisted_code = connection.execute(
                text("SELECT inventory_code FROM artworks WHERE id = :artwork_id"), {"artwork_id": artwork_id}
            ).scalar_one()
        assert persisted_code == artwork_code
    finally:
        if admin_headers:
            for kind, path in (
                ("alert", "/api/v1/alerts"),
                ("device", "/api/v1/devices"),
                ("artwork", "/api/v1/artworks"),
                ("location", "/api/v1/locations"),
            ):
                item_id = created[kind]
                if item_id is not None:
                    response = client.delete(f"{path}/{item_id}", headers=admin_headers)
                    assert response.status_code in (204, 404), response.text
        client.close()
        app.dependency_overrides.pop(get_db, None)
        engine.dispose()


def test_sql_server_artwork_image_upload_and_replacement():
    assert settings.database_url.drivername == "mssql+pyodbc"
    assert settings.db_name.casefold() == "pbl4_art_guard"

    engine = create_engine(settings.database_url, pool_pre_ping=True)
    factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)

    with engine.connect() as connection:
        server_name, database_name, version = connection.execute(
            text("SELECT @@SERVERNAME, DB_NAME(), @@VERSION")
        ).one()
    assert server_name
    assert database_name.casefold() == settings.db_name.casefold()
    assert "Microsoft SQL Server" in version

    def get_sql_server_db():
        session = factory()
        try:
            assert session.execute(text("SELECT DB_NAME()")).scalar_one().casefold() == settings.db_name.casefold()
            yield session
        finally:
            session.close()

    app.dependency_overrides[get_db] = get_sql_server_db
    client = TestClient(app)
    artwork_id = None
    admin_headers = None
    suffix = uuid4().hex[:12].upper()

    def login(user_index):
        username, _, _, password, _ = DEMO_USERS[user_index]
        response = client.post("/api/v1/auth/login", json={"username": username, "password": password})
        assert response.status_code == 200, response.text
        return {"Authorization": f"Bearer {response.json()['access_token']}"}

    def encoded_image(image_format):
        output = BytesIO()
        Image.new("RGB", (12, 10), color=(131, 150, 117)).save(output, format=image_format)
        return output.getvalue()

    try:
        admin_headers = login(0)
        manager_headers = login(1)
        operator_headers = login(2)

        artwork_response = client.post(
            "/api/v1/artworks",
            headers=manager_headers,
            json={"inventory_code": f"IMG-{suffix}", "title": f"Image upload {suffix}", "artist": "Integration Test"},
        )
        assert artwork_response.status_code == 201, artwork_response.text
        artwork_id = artwork_response.json()["id"]
        image_path = f"/api/v1/artworks/{artwork_id}/image"
        png_data = encoded_image("PNG")

        assert client.post(image_path, files={"file": ("valid.png", png_data, "image/png")}).status_code == 401
        assert client.post(image_path, headers=operator_headers, files={"file": ("valid.png", png_data, "image/png")}).status_code == 403
        assert client.post(f"/api/v1/artworks/{artwork_id + 9_000_000}/image", headers=manager_headers, files={"file": ("valid.png", png_data, "image/png")}).status_code == 404
        invalid = client.post(image_path, headers=manager_headers, files={"file": ("photo.png", b"not actually an image", "image/png")})
        assert invalid.status_code == 415, invalid.text
        oversized = client.post(image_path, headers=manager_headers, files={"file": ("large.png", b"x" * (5 * 1024 * 1024 + 1), "image/png")})
        assert oversized.status_code == 413, oversized.text

        # The bytes determine the stored type; client filename and MIME type are not trusted.
        first_upload = client.post(image_path, headers=manager_headers, files={"file": ("user-picked.jpg", png_data, "image/jpeg")})
        assert first_upload.status_code == 200, first_upload.text
        first_url = first_upload.json()["image_url"]
        assert first_url.startswith("/uploads/artworks/")
        assert first_url.endswith(".png")
        assert "user-picked" not in first_url
        first_served = client.get(first_url)
        assert first_served.status_code == 200
        assert first_served.headers["content-type"].startswith("image/png")
        assert first_served.content == png_data

        with engine.connect() as connection:
            persisted_first_url = connection.execute(
                text("SELECT image_url FROM dbo.artworks WHERE id = :artwork_id"), {"artwork_id": artwork_id}
            ).scalar_one()
        assert persisted_first_url == first_url

        failed_replacement = client.post(image_path, headers=manager_headers, files={"file": ("broken.webp", b"broken", "image/webp")})
        assert failed_replacement.status_code == 415
        assert client.get(first_url).status_code == 200
        with engine.connect() as connection:
            still_current_url = connection.execute(
                text("SELECT image_url FROM dbo.artworks WHERE id = :artwork_id"), {"artwork_id": artwork_id}
            ).scalar_one()
        assert still_current_url == first_url

        webp_data = encoded_image("WEBP")
        replacement = client.post(image_path, headers=manager_headers, files={"file": ("new-image.png", webp_data, "image/png")})
        assert replacement.status_code == 200, replacement.text
        second_url = replacement.json()["image_url"]
        assert second_url.endswith(".webp")
        assert second_url != first_url
        assert client.get(first_url).status_code == 404
        second_served = client.get(second_url)
        assert second_served.status_code == 200
        assert second_served.headers["content-type"].startswith("image/webp")
        assert second_served.content == webp_data
        with engine.connect() as connection:
            persisted_second_url = connection.execute(
                text("SELECT image_url FROM dbo.artworks WHERE id = :artwork_id"), {"artwork_id": artwork_id}
            ).scalar_one()
        assert persisted_second_url == second_url
    finally:
        if artwork_id is not None and admin_headers:
            response = client.delete(f"/api/v1/artworks/{artwork_id}", headers=admin_headers)
            assert response.status_code in (204, 404), response.text
        client.close()
        app.dependency_overrides.pop(get_db, None)
        engine.dispose()
