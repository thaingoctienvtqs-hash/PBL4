from datetime import datetime, timedelta

from sqlalchemy import select

from app.core.security import hash_password
from app.db import SessionLocal
from app.models import (Alert, AlertHistory, AlertNote, Artwork, Device, DeviceStatusHistory,
                        Location, ModelVersion, Role, SystemSetting, User)

ROLES = ["admin", "manager", "operator"]
DEMO_USERS = [
    ("admin", "admin@artguard-demo.com", "Quản trị viên", "ArtGuardDemo2026!", "admin"),
    ("manager", "manager@artguard-demo.com", "Quản lý phòng trưng bày", "GalleryDemo2026!", "manager"),
    ("operator", "operator@artguard-demo.com", "Nhân viên giám sát", "OperatorDemo2026!", "operator"),
]
LOCATION_SEED = [
    ("GALLERY-A", "Phòng Tranh Sơn Dầu", "Tầng 1 · khu trưng bày phía Đông", 40),
    ("GALLERY-B", "Phòng Nghệ Thuật Đương Đại", "Tầng 1 · khu trung tâm", 32),
    ("GALLERY-C", "Phòng Điêu Khắc", "Tầng 2 · khu phía Tây", 24),
]
ARTWORK_SEED = [
    ("AG-001", "Chiều bên hiên", "Nguyễn An", 1987, "Sơn dầu trên toan", "GALLERY-A"),
    ("AG-002", "Dòng sông mùa hạ", "Trần Minh", 1994, "Sơn mài", "GALLERY-A"),
    ("AG-003", "Miền ký ức", "Lê Hà", 2003, "Acrylic", "GALLERY-A"),
    ("AG-004", "Vệt nắng", "Phạm Duy", 2011, "Màu nước", "GALLERY-B"),
    ("AG-005", "Những đường cong", "Vũ Linh", 2019, "Sơn dầu trên toan", "GALLERY-B"),
    ("AG-006", "Mạch đất", "Đỗ Mai", 2008, "Chất liệu tổng hợp", "GALLERY-B"),
    ("AG-007", "Tĩnh vật số 4", "Hoàng Nam", 1978, "Sơn dầu trên gỗ", "GALLERY-C"),
    ("AG-008", "Khoảng lặng", "Bùi Vy", 2022, "Sơn mài", "GALLERY-C"),
]
DEVICE_SEED = [
    ("CAM-A01", "Camera lối vào Đông", "GALLERY-A", "AG-001", "online"),
    ("CAM-A02", "Camera tường phía Bắc", "GALLERY-A", "AG-002", "online"),
    ("CAM-B01", "Camera sảnh trung tâm", "GALLERY-B", "AG-004", "online"),
    ("CAM-C01", "Camera khu điêu khắc", "GALLERY-C", "AG-007", "offline"),
]
ALERT_TITLES = ["Tiếp cận gần tác phẩm", "Lưu ý khoảng cách an toàn", "Khu vực giám sát cần kiểm tra", "Sự kiện mô phỏng: phát hiện chuyển động", "Nhắc nhở kiểm tra hiện trường"]
SEVERITIES = ["low", "medium", "high", "critical"]
STATUSES = ["new", "acknowledged", "investigating", "resolved", "false_positive"]


def run_seed(session_factory=SessionLocal) -> dict[str, int]:
    db = session_factory()
    try:
        role_map = {}
        for name in ROLES:
            role = db.scalar(select(Role).where(Role.name == name))
            if not role:
                role = Role(name=name)
                db.add(role)
            role_map[name] = role
        db.flush()

        for username, email, full_name, password, role_name in DEMO_USERS:
            user = db.scalar(select(User).where(User.username == username))
            if not user:
                user = User(username=username, email=email, full_name=full_name, password_hash=hash_password(password), roles=[role_map[role_name]])
                db.add(user)
            else:
                user.email = email
                user.full_name = full_name
                if role_map[role_name] not in user.roles:
                    user.roles.append(role_map[role_name])
        db.flush()
        demo_user = db.scalar(select(User).where(User.username == "manager"))

        locations = {}
        for code, name, description, capacity in LOCATION_SEED:
            item = db.scalar(select(Location).where(Location.code == code))
            if not item:
                item = Location(code=code, name=name, description=description, capacity=capacity)
                db.add(item)
            locations[code] = item
        db.flush()

        artworks = {}
        for code, title, artist, year, medium, location_code in ARTWORK_SEED:
            item = db.scalar(select(Artwork).where(Artwork.inventory_code == code))
            if not item:
                item = Artwork(inventory_code=code, title=title, artist=artist, year_created=year, medium=medium, description="Bản ghi mẫu phục vụ giao diện và kiểm thử nghiệp vụ.", status="displayed", location=locations[location_code])
                db.add(item)
            artworks[code] = item
        db.flush()

        devices = {}
        for code, name, location_code, artwork_code, device_status in DEVICE_SEED:
            item = db.scalar(select(Device).where(Device.device_code == code))
            if not item:
                item = Device(device_code=code, name=name, device_type="simulated_camera", status=device_status, location=locations[location_code], artwork=artworks[artwork_code], notes="Thiết bị mô phỏng; chưa kết nối phần cứng.", last_seen_at=datetime.utcnow() if device_status == "online" else None)
                db.add(item)
            devices[code] = item
        db.flush()
        for item in devices.values():
            if not db.scalar(select(DeviceStatusHistory.id).where(DeviceStatusHistory.device_id == item.id)):
                db.add(DeviceStatusHistory(device_id=item.id, status=item.status))

        for index in range(24):
            code = f"DEMO-SEED-{index + 1:03d}"
            item = db.scalar(select(Alert).where(Alert.event_code == code))
            if item:
                continue
            status = STATUSES[index % len(STATUSES)]
            detected = datetime.utcnow() - timedelta(days=index % 14, hours=(index * 3) % 24)
            item = Alert(event_code=code, title=ALERT_TITLES[index % len(ALERT_TITLES)], description="Sự kiện dữ liệu mẫu để minh họa quy trình giám sát. Không phải kết quả AI thực tế.", severity=SEVERITIES[index % len(SEVERITIES)], status=status, source="demo", detected_at=detected, resolved_at=detected + timedelta(minutes=12) if status in {"resolved", "false_positive"} else None, artwork=artworks[ARTWORK_SEED[index % len(ARTWORK_SEED)][0]], device=devices[DEVICE_SEED[index % len(DEVICE_SEED)][0]])
            db.add(item)
            db.flush()
            db.add(AlertHistory(alert_id=item.id, user_id=demo_user.id, to_status="new", note="Khởi tạo từ dữ liệu demo"))
            if index % 3 == 0:
                db.add(AlertNote(alert_id=item.id, user_id=demo_user.id, content="Bản ghi mô phỏng: cần đối chiếu trực tiếp tại phòng trưng bày."))

        for name, version, notes in [("ArtGuard Contact Demo", "demo-1.0", "Nhãn mô phỏng; chưa kết nối model."), ("ArtGuard Contact Demo", "demo-0.9", "Phiên bản minh họa."), ("ArtGuard Motion Demo", "demo-0.4", "Không phải kết quả huấn luyện thực tế.")]:
            if not db.scalar(select(ModelVersion.id).where(ModelVersion.name == name, ModelVersion.version == version)):
                db.add(ModelVersion(name=name, version=version, status="demo", is_demo=True, notes=notes))

        defaults = {"demo_alerts_enabled": "true", "demo_alert_interval_seconds": "45", "system_display_name": "ArtGuard", "data_mode": "demo"}
        for key, value in defaults.items():
            if not db.get(SystemSetting, key):
                db.add(SystemSetting(key=key, value=value, updated_by=demo_user.id))
        db.commit()
        return {"roles": len(ROLES), "users": len(DEMO_USERS), "locations": len(LOCATION_SEED), "artworks": len(ARTWORK_SEED), "devices": len(DEVICE_SEED), "alerts": 24, "model_versions": 3}
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


if __name__ == "__main__":
    result = run_seed()
    print("Đã seed dữ liệu mẫu (chạy lặp lại an toàn):")
    for name, count in result.items():
        print(f"- {name}: {count}")
