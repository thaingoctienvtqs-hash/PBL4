from datetime import datetime
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.audit import record_audit
from app.db import get_db
from app.dependencies import get_current_user, require_roles
from app.models import Alert, AlertHistory, AlertNote, Artwork, Device, User
from app.schemas import AlertCreate, AlertHistoryOut, AlertNoteCreate, AlertNoteOut, AlertOut, AlertStatusUpdate, Page
from app.api.resources import alert_output

router = APIRouter(prefix="/alerts", tags=["alerts"])


@router.get("", response_model=Page[AlertOut])
def list_alerts(q: str | None = None, status_filter: str | None = Query(None, alias="status"), severity: str | None = None, source: str | None = None, page_number: int = Query(1, alias="page", ge=1), page_size: int = Query(20, ge=1, le=100), _: User = Depends(get_current_user), db: Session = Depends(get_db)):
    stmt = select(Alert).outerjoin(Artwork).outerjoin(Device)
    if q:
        needle = f"%{q.strip()}%"
        stmt = stmt.where(or_(Alert.title.like(needle), Alert.event_code.like(needle), Artwork.title.like(needle), Device.name.like(needle)))
    if status_filter:
        stmt = stmt.where(Alert.status == status_filter)
    if severity:
        stmt = stmt.where(Alert.severity == severity)
    if source:
        stmt = stmt.where(Alert.source == source)
    total = db.scalar(select(func.count()).select_from(stmt.order_by(None).subquery())) or 0
    items = db.scalars(stmt.order_by(Alert.detected_at.desc()).offset((page_number - 1) * page_size).limit(page_size)).all()
    return Page(items=[alert_output(item) for item in items], total=total, page=page_number, page_size=page_size)


@router.post("", response_model=AlertOut, status_code=201)
def create_demo_alert(payload: AlertCreate, user: User = Depends(require_roles("admin", "manager")), db: Session = Depends(get_db)):
    if payload.artwork_id and not db.get(Artwork, payload.artwork_id):
        raise HTTPException(422, "Tranh không tồn tại")
    if payload.device_id and not db.get(Device, payload.device_id):
        raise HTTPException(422, "Thiết bị không tồn tại")
    item = Alert(event_code=f"DEMO-{uuid4().hex[:10].upper()}", title=payload.title, description=payload.description, severity=payload.severity, status="new", source="demo", detected_at=datetime.utcnow(), artwork_id=payload.artwork_id, device_id=payload.device_id)
    db.add(item)
    db.flush()
    db.add(AlertHistory(alert_id=item.id, user_id=user.id, to_status="new", note="Tạo sự kiện mô phỏng"))
    record_audit(db, user, "create_demo_alert", "alert", item.id, "source=demo")
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(409, "Không thể tạo sự kiện mô phỏng") from exc
    db.refresh(item)
    return alert_output(item)


@router.patch("/{alert_id}/status", response_model=AlertOut)
def update_status(alert_id: int, payload: AlertStatusUpdate, user: User = Depends(require_roles("admin", "manager", "operator")), db: Session = Depends(get_db)):
    item = db.get(Alert, alert_id)
    if not item:
        raise HTTPException(404, "Không tìm thấy cảnh báo")
    previous = item.status
    if previous in {"resolved", "false_positive"} and payload.status not in {previous}:
        raise HTTPException(409, "Cảnh báo đã kết thúc; không thể mở lại từ giao diện này")
    item.status = payload.status
    item.resolved_at = datetime.utcnow() if payload.status in {"resolved", "false_positive"} else None
    db.add(AlertHistory(alert_id=item.id, user_id=user.id, from_status=previous, to_status=payload.status, note=payload.note))
    if payload.note:
        db.add(AlertNote(alert_id=item.id, user_id=user.id, content=payload.note))
    record_audit(db, user, "change_status", "alert", item.id, f"{previous} -> {payload.status}")
    db.commit()
    db.refresh(item)
    return alert_output(item)


@router.get("/{alert_id}/history", response_model=list[AlertHistoryOut])
def alert_history(alert_id: int, _: User = Depends(get_current_user), db: Session = Depends(get_db)):
    if not db.get(Alert, alert_id):
        raise HTTPException(404, "Không tìm thấy cảnh báo")
    rows = db.scalars(select(AlertHistory).where(AlertHistory.alert_id == alert_id).order_by(AlertHistory.changed_at.desc())).all()
    return [AlertHistoryOut(id=row.id, from_status=row.from_status, to_status=row.to_status, note=row.note, changed_at=row.changed_at, user_name=row.user.full_name if row.user else None) for row in rows]


@router.get("/{alert_id}/notes", response_model=list[AlertNoteOut])
def list_notes(alert_id: int, _: User = Depends(get_current_user), db: Session = Depends(get_db)):
    if not db.get(Alert, alert_id):
        raise HTTPException(404, "Không tìm thấy cảnh báo")
    rows = db.scalars(select(AlertNote).where(AlertNote.alert_id == alert_id).order_by(AlertNote.created_at.desc())).all()
    return [AlertNoteOut(id=row.id, content=row.content, created_at=row.created_at, user_name=row.user.full_name) for row in rows]


@router.post("/{alert_id}/notes", response_model=AlertNoteOut, status_code=201)
def add_note(alert_id: int, payload: AlertNoteCreate, user: User = Depends(require_roles("admin", "manager", "operator")), db: Session = Depends(get_db)):
    if not db.get(Alert, alert_id):
        raise HTTPException(404, "Không tìm thấy cảnh báo")
    note = AlertNote(alert_id=alert_id, user_id=user.id, content=payload.content.strip())
    db.add(note)
    db.flush()
    record_audit(db, user, "add_note", "alert", alert_id)
    db.commit()
    db.refresh(note)
    return AlertNoteOut(id=note.id, content=note.content, created_at=note.created_at, user_name=user.full_name)


@router.delete("/{alert_id}", status_code=204)
def delete_demo_alert(alert_id: int, user: User = Depends(require_roles("admin")), db: Session = Depends(get_db)):
    item = db.get(Alert, alert_id)
    if not item:
        raise HTTPException(404, "Không tìm thấy cảnh báo")
    if item.source != "demo":
        raise HTTPException(403, "Chỉ có thể xóa cảnh báo mô phỏng")
    record_audit(db, user, "delete_demo_alert", "alert", item.id, item.event_code)
    db.delete(item)
    db.commit()
    return None
