from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from sqlalchemy import func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.audit import record_audit
from app.artwork_images import delete_managed_artwork_image
from app.db import get_db
from app.dependencies import get_current_user, require_roles
from app.models import Alert, Artwork, Device, DeviceStatusHistory, Location, User
from app.schemas import (AlertOut, ArtworkCreate, ArtworkOut, ArtworkUpdate, DeviceCreate, DeviceOut,
                         DeviceUpdate, DeviceStreamUpdate, LocationCreate, LocationOut, LocationUpdate, Page)

router = APIRouter(tags=["collection management"])


def page(db: Session, statement, model, page_number: int, page_size: int):
    total = db.scalar(select(func.count()).select_from(statement.order_by(None).subquery())) or 0
    items = db.scalars(statement.offset((page_number - 1) * page_size).limit(page_size)).all()
    return items, total


def commit_or_conflict(db: Session, message: str):
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail=message) from exc


def flush_or_conflict(db: Session, message: str):
    try:
        db.flush()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail=message) from exc


def artwork_output(item: Artwork) -> ArtworkOut:
    return ArtworkOut.model_validate(item).model_copy(update={"location_name": item.location.name if item.location else None})


def device_output(item: Device) -> DeviceOut:
    return DeviceOut.model_validate(item).model_copy(update={
        "location_name": item.location.name if item.location else None,
        "artwork_title": item.artwork.title if item.artwork else None,
        "stream_url": item.stream_url,
        "stream_type": item.stream_type,
    })


@router.get("/roles", response_model=list[str])
def list_roles(_: User = Depends(get_current_user), db: Session = Depends(get_db)):
    from app.models import Role
    return [role.name for role in db.scalars(select(Role).order_by(Role.name)).all()]


@router.get("/locations", response_model=Page[LocationOut])
def list_locations(q: str | None = None, active: bool | None = None, page_number: int = Query(1, alias="page", ge=1), page_size: int = Query(20, ge=1, le=100), _: User = Depends(get_current_user), db: Session = Depends(get_db)):
    stmt = select(Location)
    if q:
        needle = f"%{q.strip()}%"
        stmt = stmt.where(or_(Location.name.like(needle), Location.code.like(needle), Location.description.like(needle)))
    if active is not None:
        stmt = stmt.where(Location.is_active.is_(active))
    stmt = stmt.order_by(Location.name)
    items, total = page(db, stmt, Location, page_number, page_size)
    return Page(items=items, total=total, page=page_number, page_size=page_size)


@router.post("/locations", response_model=LocationOut, status_code=201)
def create_location(payload: LocationCreate, user: User = Depends(require_roles("admin", "manager")), db: Session = Depends(get_db)):
    item = Location(**payload.model_dump())
    db.add(item)
    flush_or_conflict(db, "Mã khu vực đã tồn tại")
    record_audit(db, user, "create", "location", item.id, item.code)
    commit_or_conflict(db, "Mã khu vực đã tồn tại")
    db.refresh(item)
    return item


@router.get("/locations/{item_id}", response_model=LocationOut)
def get_location(item_id: int, _: User = Depends(get_current_user), db: Session = Depends(get_db)):
    item = db.get(Location, item_id)
    if not item:
        raise HTTPException(404, "Không tìm thấy khu vực")
    return item


@router.patch("/locations/{item_id}", response_model=LocationOut)
def update_location(item_id: int, payload: LocationUpdate, user: User = Depends(require_roles("admin", "manager")), db: Session = Depends(get_db)):
    item = db.get(Location, item_id)
    if not item:
        raise HTTPException(404, "Không tìm thấy khu vực")
    for key, value in payload.model_dump(exclude_unset=True).items():
        setattr(item, key, value)
    record_audit(db, user, "update", "location", item.id)
    commit_or_conflict(db, "Mã khu vực đã được sử dụng")
    db.refresh(item)
    return item


@router.delete("/locations/{item_id}", status_code=204)
def delete_location(item_id: int, user: User = Depends(require_roles("admin")), db: Session = Depends(get_db)):
    item = db.get(Location, item_id)
    if not item:
        raise HTTPException(404, "Không tìm thấy khu vực")
    record_audit(db, user, "delete", "location", item.id, item.code)
    db.delete(item)
    db.commit()
    return Response(status_code=204)


@router.get("/artworks", response_model=Page[ArtworkOut])
def list_artworks(q: str | None = None, status_filter: str | None = Query(None, alias="status"), location_id: int | None = None, page_number: int = Query(1, alias="page", ge=1), page_size: int = Query(20, ge=1, le=100), _: User = Depends(get_current_user), db: Session = Depends(get_db)):
    stmt = select(Artwork).outerjoin(Location)
    if q:
        needle = f"%{q.strip()}%"
        stmt = stmt.where(or_(Artwork.title.like(needle), Artwork.artist.like(needle), Artwork.inventory_code.like(needle)))
    if status_filter:
        stmt = stmt.where(Artwork.status == status_filter)
    if location_id:
        stmt = stmt.where(Artwork.location_id == location_id)
    stmt = stmt.order_by(Artwork.updated_at.desc())
    items, total = page(db, stmt, Artwork, page_number, page_size)
    return Page(items=[artwork_output(item) for item in items], total=total, page=page_number, page_size=page_size)


@router.post("/artworks", response_model=ArtworkOut, status_code=201)
def create_artwork(payload: ArtworkCreate, user: User = Depends(require_roles("admin", "manager")), db: Session = Depends(get_db)):
    values = payload.model_dump()
    if values["location_id"] and not db.get(Location, values["location_id"]):
        raise HTTPException(422, "Khu vực không tồn tại")
    item = Artwork(**values)
    db.add(item)
    flush_or_conflict(db, "Mã tranh đã tồn tại")
    record_audit(db, user, "create", "artwork", item.id, item.inventory_code)
    commit_or_conflict(db, "Mã tranh đã tồn tại")
    db.refresh(item)
    return artwork_output(item)


@router.get("/artworks/{item_id}", response_model=ArtworkOut)
def get_artwork(item_id: int, _: User = Depends(get_current_user), db: Session = Depends(get_db)):
    item = db.get(Artwork, item_id)
    if not item:
        raise HTTPException(404, "Không tìm thấy tranh")
    return artwork_output(item)


@router.patch("/artworks/{item_id}", response_model=ArtworkOut)
def update_artwork(item_id: int, payload: ArtworkUpdate, user: User = Depends(require_roles("admin", "manager")), db: Session = Depends(get_db)):
    item = db.get(Artwork, item_id)
    if not item:
        raise HTTPException(404, "Không tìm thấy tranh")
    values = payload.model_dump(exclude_unset=True)
    if values.get("location_id") and not db.get(Location, values["location_id"]):
        raise HTTPException(422, "Khu vực không tồn tại")
    for key, value in values.items():
        setattr(item, key, value)
    record_audit(db, user, "update", "artwork", item.id)
    commit_or_conflict(db, "Mã tranh đã được sử dụng")
    db.refresh(item)
    return artwork_output(item)


@router.get("/artworks/{item_id}/alerts", response_model=list[AlertOut])
def artwork_alerts(item_id: int, _: User = Depends(get_current_user), db: Session = Depends(get_db)):
    if not db.get(Artwork, item_id):
        raise HTTPException(404, "Không tìm thấy tranh")
    rows = db.scalars(select(Alert).where(Alert.artwork_id == item_id).order_by(Alert.detected_at.desc()).limit(100)).all()
    return [alert_output(item) for item in rows]


@router.delete("/artworks/{item_id}", status_code=204)
def delete_artwork(item_id: int, user: User = Depends(require_roles("admin")), db: Session = Depends(get_db)):
    item = db.get(Artwork, item_id)
    if not item:
        raise HTTPException(404, "Không tìm thấy tranh")
    record_audit(db, user, "delete", "artwork", item.id, item.inventory_code)
    image_url = item.image_url
    db.delete(item)
    db.commit()
    delete_managed_artwork_image(image_url)
    return Response(status_code=204)


@router.get("/devices", response_model=Page[DeviceOut])
def list_devices(q: str | None = None, status_filter: str | None = Query(None, alias="status"), location_id: int | None = None, page_number: int = Query(1, alias="page", ge=1), page_size: int = Query(20, ge=1, le=100), _: User = Depends(get_current_user), db: Session = Depends(get_db)):
    stmt = select(Device).outerjoin(Location)
    if q:
        needle = f"%{q.strip()}%"
        stmt = stmt.where(or_(Device.name.like(needle), Device.device_code.like(needle), Device.device_type.like(needle)))
    if status_filter:
        stmt = stmt.where(Device.status == status_filter)
    if location_id:
        stmt = stmt.where(Device.location_id == location_id)
    stmt = stmt.order_by(Device.name)
    items, total = page(db, stmt, Device, page_number, page_size)
    return Page(items=[device_output(item) for item in items], total=total, page=page_number, page_size=page_size)


@router.post("/devices", response_model=DeviceOut, status_code=201)
def create_device(payload: DeviceCreate, user: User = Depends(require_roles("admin", "manager")), db: Session = Depends(get_db)):
    values = payload.model_dump()
    if values["location_id"] and not db.get(Location, values["location_id"]):
        raise HTTPException(422, "Khu vực không tồn tại")
    if values["artwork_id"] and not db.get(Artwork, values["artwork_id"]):
        raise HTTPException(422, "Tranh không tồn tại")
    item = Device(**values, last_seen_at=datetime.utcnow() if values["status"] == "online" else None)
    db.add(item)
    flush_or_conflict(db, "Mã thiết bị đã tồn tại")
    db.add(DeviceStatusHistory(device_id=item.id, status=item.status))
    record_audit(db, user, "create", "device", item.id, item.device_code)
    commit_or_conflict(db, "Mã thiết bị đã tồn tại")
    db.refresh(item)
    return device_output(item)


@router.patch("/devices/{item_id}", response_model=DeviceOut)
def update_device(item_id: int, payload: DeviceUpdate, user: User = Depends(require_roles("admin", "manager")), db: Session = Depends(get_db)):
    item = db.get(Device, item_id)
    if not item:
        raise HTTPException(404, "Không tìm thấy thiết bị")
    values = payload.model_dump(exclude_unset=True)
    if values.get("location_id") and not db.get(Location, values["location_id"]):
        raise HTTPException(422, "Khu vực không tồn tại")
    if values.get("artwork_id") and not db.get(Artwork, values["artwork_id"]):
        raise HTTPException(422, "Tranh không tồn tại")
    old_status = item.status
    for key, value in values.items():
        setattr(item, key, value)
    if item.status == "online":
        item.last_seen_at = datetime.utcnow()
    if item.status != old_status:
        db.add(DeviceStatusHistory(device_id=item.id, status=item.status))
    record_audit(db, user, "update", "device", item.id)
    commit_or_conflict(db, "Mã thiết bị đã được sử dụng")
    db.refresh(item)
    return device_output(item)


@router.get("/devices/{item_id}/history")
def device_history(item_id: int, _: User = Depends(get_current_user), db: Session = Depends(get_db)):
    if not db.get(Device, item_id):
        raise HTTPException(404, "Không tìm thấy thiết bị")
    rows = db.scalars(select(DeviceStatusHistory).where(DeviceStatusHistory.device_id == item_id).order_by(DeviceStatusHistory.recorded_at.desc()).limit(100)).all()
    return [{"id": row.id, "status": row.status, "recorded_at": row.recorded_at} for row in rows]


@router.delete("/devices/{item_id}", status_code=204)
def delete_device(item_id: int, user: User = Depends(require_roles("admin")), db: Session = Depends(get_db)):
    item = db.get(Device, item_id)
    if not item:
        raise HTTPException(404, "Không tìm thấy thiết bị")
    record_audit(db, user, "delete", "device", item.id, item.device_code)
    db.delete(item)
    db.commit()
    return Response(status_code=204)


@router.patch("/devices/{item_id}/stream", response_model=DeviceOut)
def update_device_stream(item_id: int, payload: DeviceStreamUpdate, user: User = Depends(require_roles("admin", "manager")), db: Session = Depends(get_db)):
    """Cập nhật cấu hình nguồn stream cho camera. Không thay đổi trạng thái kết nối thực tế."""
    item = db.get(Device, item_id)
    if not item:
        raise HTTPException(404, "Không tìm thấy thiết bị")
    for key, value in payload.model_dump(exclude_unset=True).items():
        setattr(item, key, value)
    record_audit(db, user, "update_stream", "device", item.id)
    commit_or_conflict(db, "Lỗi cập nhật stream")
    db.refresh(item)
    return device_output(item)


def alert_output(item: Alert) -> AlertOut:
    return AlertOut(id=item.id, event_code=item.event_code, title=item.title, description=item.description, severity=item.severity, status=item.status, source=item.source, detected_at=item.detected_at, resolved_at=item.resolved_at, artwork_id=item.artwork_id, artwork_title=item.artwork.title if item.artwork else None, device_id=item.device_id, device_name=item.device.name if item.device else None, assigned_user_id=item.assigned_user_id)
