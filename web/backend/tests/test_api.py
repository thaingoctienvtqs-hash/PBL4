def token(client, username):
    response = client.post("/api/v1/auth/login", json={"username": username, "password": "TestPassword2026!"})
    assert response.status_code == 200
    return response.json()["access_token"]


def headers(value):
    return {"Authorization": f"Bearer {value}"}


def test_login_and_protected_dashboard(database):
    client, _ = database
    assert client.get("/api/v1/dashboard").status_code == 401
    assert client.post("/api/v1/auth/login", json={"username": "admin", "password": "incorrect-password"}).status_code == 401
    response = client.get("/api/v1/dashboard", headers=headers(token(client, "admin")))
    assert response.status_code == 200
    assert response.json()["metrics"]["artworks"] == 0
    assert response.json()["data_mode"] == "demo"


def test_role_guard_and_artwork_crud(database):
    client, _ = database
    manager = headers(token(client, "manager"))
    operator = headers(token(client, "operator"))
    location_payload = {"code": "G-1", "name": "Phòng mẫu"}
    assert client.post("/api/v1/locations", headers=manager, json=location_payload).status_code == 201
    assert client.post("/api/v1/locations", headers=manager, json=location_payload).status_code == 409
    location_id = client.get("/api/v1/locations", headers=manager).json()["items"][0]["id"]
    payload = {"inventory_code": "TEST-01", "title": "Tranh thử", "artist": "Nguyễn An", "location_id": location_id, "status": "displayed"}
    assert client.post("/api/v1/artworks", headers=operator, json=payload).status_code == 403
    created = client.post("/api/v1/artworks", headers=manager, json=payload)
    assert created.status_code == 201
    assert client.post("/api/v1/artworks", headers=manager, json=payload).status_code == 409
    assert created.json()["location_name"] == "Phòng mẫu"
    assert client.get("/api/v1/artworks?q=TEST-01", headers=manager).json()["total"] == 1
    assert client.get(f"/api/v1/artworks/{created.json()['id']}", headers=manager).status_code == 200


def test_operator_can_update_alert_and_history_is_recorded(database):
    client, factory = database
    manager = headers(token(client, "manager"))
    operator = headers(token(client, "operator"))
    alert = client.post("/api/v1/alerts", headers=manager, json={"title": "Sự kiện thử", "description": "Sự kiện tạo trong kiểm thử", "severity": "high"})
    assert alert.status_code == 201
    alert_id = alert.json()["id"]
    result = client.patch(f"/api/v1/alerts/{alert_id}/status", headers=operator, json={"status": "investigating", "note": "Đang rà soát"})
    assert result.status_code == 200
    assert result.json()["status"] == "investigating"
    history = client.get(f"/api/v1/alerts/{alert_id}/history", headers=operator)
    assert history.status_code == 200
    assert len(history.json()) == 2
    assert history.json()[0]["to_status"] == "investigating"


def test_device_crud_validation_and_not_found(database):
    client, _ = database
    manager = headers(token(client, "manager"))
    operator = headers(token(client, "operator"))
    location = client.post("/api/v1/locations", headers=manager, json={"code": "G-2", "name": "Phòng thiết bị"}).json()
    assert client.get(f"/api/v1/locations/{location['id']}", headers=manager).status_code == 200
    payload = {"device_code": "CAM-T1", "name": "Camera mẫu", "location_id": location["id"], "status": "online"}
    assert client.post("/api/v1/devices", headers=operator, json=payload).status_code == 403
    created = client.post("/api/v1/devices", headers=manager, json=payload)
    assert created.status_code == 201
    assert client.post("/api/v1/devices", headers=manager, json=payload).status_code == 409
    device_id = created.json()["id"]
    assert created.json()["location_name"] == "Phòng thiết bị"
    assert client.get("/api/v1/devices?q=CAM-T1", headers=manager).json()["total"] == 1
    assert client.patch(f"/api/v1/devices/{device_id}", headers=manager, json={"status": "offline"}).json()["status"] == "offline"
    device_history = client.get(f"/api/v1/devices/{device_id}/history", headers=manager)
    assert [entry["status"] for entry in device_history.json()] == ["offline", "online"]
    assert client.patch(f"/api/v1/devices/{device_id}", headers=manager, json={"status": "unknown"}).status_code == 422
    assert client.patch("/api/v1/devices/99999", headers=manager, json={"status": "offline"}).status_code == 404


def test_reports_query_database_and_admin_endpoints_are_protected(database):
    client, _ = database
    manager = headers(token(client, "manager"))
    operator = headers(token(client, "operator"))
    admin = headers(token(client, "admin"))
    assert client.post("/api/v1/alerts", headers=manager, json={"title": "Thử báo cáo", "description": "Sự kiện kiểm thử database", "severity": "critical"}).status_code == 201
    report = client.get("/api/v1/reports/summary?days=7", headers=manager)
    assert report.status_code == 200
    assert sum(point["count"] for point in report.json()["trend"]) == 1
    assert report.json()["metrics"]["critical_alerts"] == 1
    assert client.get("/api/v1/users", headers=operator).status_code == 403
    assert client.get("/api/v1/users", headers=admin).status_code == 200
    assert client.get("/api/v1/roles", headers=manager).json() == ["admin", "manager", "operator"]


def test_demo_seed_is_repeatable(database):
    from sqlalchemy import func, select

    from app.models import Alert, Artwork, Device, Location, ModelVersion, User
    from seed_demo import run_seed

    _, factory = database
    run_seed(factory)
    run_seed(factory)
    session = factory()
    try:
        assert session.scalar(select(func.count(User.id))) == 3  # the seed reuses the same demo usernames
        assert session.scalar(select(func.count(Location.id))) == 3
        assert session.scalar(select(func.count(Artwork.id))) == 8
        assert session.scalar(select(func.count(Device.id))) == 4
        assert session.scalar(select(func.count(Alert.id))) == 24
        assert session.scalar(select(func.count(ModelVersion.id))) == 3
    finally:
        session.close()
