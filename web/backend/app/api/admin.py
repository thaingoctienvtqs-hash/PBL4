from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.audit import record_audit
from app.core.security import hash_password
from app.db import get_db
from app.dependencies import require_roles
from app.models import AuditLog, ModelVersion, Role, SystemSetting, User
from app.schemas import ModelVersionCreate, Page, SettingOut, SettingUpdate, UserCreate, UserOut, UserUpdate
from app.api.auth import user_response

router = APIRouter(tags=["administration"])


@router.get("/users", response_model=Page[UserOut])
def list_users(q: str | None = None, page_number: int = Query(1, alias="page", ge=1), page_size: int = Query(20, ge=1, le=100), _: User = Depends(require_roles("admin")), db: Session = Depends(get_db)):
    stmt = select(User)
    if q:
        needle = f"%{q.strip()}%"
        stmt = stmt.where(or_(User.username.like(needle), User.full_name.like(needle), User.email.like(needle)))
    total = db.scalar(select(func.count()).select_from(stmt.order_by(None).subquery())) or 0
    rows = db.scalars(stmt.order_by(User.full_name).offset((page_number - 1) * page_size).limit(page_size)).all()
    return Page(items=[user_response(user) for user in rows], total=total, page=page_number, page_size=page_size)


@router.post("/users", response_model=UserOut, status_code=201)
def create_user(payload: UserCreate, actor: User = Depends(require_roles("admin")), db: Session = Depends(get_db)):
    roles = db.scalars(select(Role).where(Role.name.in_(payload.roles))).all()
    if len({role.name for role in roles}) != len(set(payload.roles)):
        raise HTTPException(422, "Vai trò không hợp lệ")
    user = User(username=payload.username, email=str(payload.email), full_name=payload.full_name, password_hash=hash_password(payload.password), roles=roles)
    db.add(user)
    try:
        db.flush()
        record_audit(db, actor, "create", "user", user.id, f"username={user.username}; roles={','.join(payload.roles)}")
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(409, "Tên đăng nhập hoặc email đã được sử dụng") from exc
    db.refresh(user)
    return user_response(user)


@router.patch("/users/{user_id}", response_model=UserOut)
def update_user(user_id: int, payload: UserUpdate, actor: User = Depends(require_roles("admin")), db: Session = Depends(get_db)):
    target = db.get(User, user_id)
    if not target:
        raise HTTPException(404, "Không tìm thấy tài khoản")
    values = payload.model_dump(exclude_unset=True)
    if target.id == actor.id and (values.get("is_active") is False or "admin" not in values.get("roles", [role.name for role in target.roles])):
        raise HTTPException(400, "Không thể tự khóa hoặc tự bỏ vai trò admin")
    if "roles" in values:
        roles = db.scalars(select(Role).where(Role.name.in_(values["roles"]))).all()
        if len({role.name for role in roles}) != len(set(values["roles"])):
            raise HTTPException(422, "Vai trò không hợp lệ")
        target.roles = roles
    for key in ("email", "full_name", "is_active"):
        if key in values:
            setattr(target, key, values[key])
    record_audit(db, actor, "update", "user", target.id, f"active={target.is_active}")
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(409, "Email đã được sử dụng") from exc
    db.refresh(target)
    return user_response(target)


@router.get("/models")
def list_models(_: User = Depends(require_roles("admin", "manager", "operator")), db: Session = Depends(get_db)):
    rows = db.scalars(select(ModelVersion).order_by(ModelVersion.created_at.desc())).all()
    return [{"id": row.id, "name": row.name, "version": row.version, "status": row.status, "is_demo": row.is_demo, "notes": row.notes, "created_at": row.created_at} for row in rows]


@router.post("/models", status_code=201)
def create_model_version(payload: ModelVersionCreate, actor: User = Depends(require_roles("admin", "manager")), db: Session = Depends(get_db)):
    if db.scalar(select(ModelVersion.id).where(ModelVersion.name == payload.name, ModelVersion.version == payload.version)):
        raise HTTPException(409, "Tên và phiên bản mô hình đã tồn tại")
    item = ModelVersion(name=payload.name, version=payload.version, status="demo", is_demo=True, notes=payload.notes)
    db.add(item)
    record_audit(db, actor, "create", "model_version", detail=f"name={payload.name}; version={payload.version}; demo=true")
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(409, "Tên và phiên bản mô hình đã tồn tại") from exc
    db.refresh(item)
    return {"id": item.id, "name": item.name, "version": item.version, "status": item.status, "is_demo": item.is_demo, "notes": item.notes, "created_at": item.created_at}


@router.patch("/models/{model_id}/status")
def update_model_status(model_id: int, status_value: str = Query(..., alias="status", pattern=r"^(demo|inactive|active)$"), actor: User = Depends(require_roles("admin", "manager")), db: Session = Depends(get_db)):
    item = db.get(ModelVersion, model_id)
    if not item:
        raise HTTPException(404, "Không tìm thấy phiên bản mô hình")
    if status_value == "active":
        db.query(ModelVersion).filter(ModelVersion.name == item.name).update({"status": "inactive"})
    item.status = status_value
    record_audit(db, actor, "update_status", "model_version", item.id, f"status={status_value}")
    db.commit()
    return {"id": item.id, "name": item.name, "version": item.version, "status": item.status, "is_demo": item.is_demo}


@router.get("/settings", response_model=list[SettingOut])
def list_settings(_: User = Depends(require_roles("admin", "manager")), db: Session = Depends(get_db)):
    return db.scalars(select(SystemSetting).order_by(SystemSetting.key)).all()


@router.put("/settings/{key}", response_model=SettingOut)
def update_setting(key: str, payload: SettingUpdate, actor: User = Depends(require_roles("admin")), db: Session = Depends(get_db)):
    item = db.get(SystemSetting, key)
    if not item:
        raise HTTPException(404, "Không tìm thấy cài đặt")
    item.value = payload.value
    item.updated_by = actor.id
    record_audit(db, actor, "update", "setting", detail=f"key={key}")
    db.commit()
    db.refresh(item)
    return item


@router.get("/audit-logs")
def list_audit_logs(page_number: int = Query(1, alias="page", ge=1), page_size: int = Query(25, ge=1, le=100), entity_type: str | None = None, _: User = Depends(require_roles("admin")), db: Session = Depends(get_db)):
    stmt = select(AuditLog)
    if entity_type:
        stmt = stmt.where(AuditLog.entity_type == entity_type)
    total = db.scalar(select(func.count()).select_from(stmt.order_by(None).subquery())) or 0
    rows = db.scalars(stmt.order_by(AuditLog.created_at.desc()).offset((page_number - 1) * page_size).limit(page_size)).all()
    return {"items": [{"id": row.id, "actor": row.user.full_name if row.user else "Hệ thống", "action": row.action, "entity_type": row.entity_type, "entity_id": row.entity_id, "result": row.result, "detail": row.detail, "created_at": row.created_at} for row in rows], "total": total, "page": page_number, "page_size": page_size}
