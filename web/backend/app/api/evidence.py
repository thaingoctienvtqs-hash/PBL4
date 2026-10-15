"""Evidence (bằng chứng vi phạm) API.

Routes:
  GET  /evidences                – danh sách, tìm kiếm, lọc, phân trang
  POST /evidences                – tạo bằng chứng mới
  GET  /evidences/{id}           – chi tiết + media + history
  PATCH /evidences/{id}/status   – cập nhật trạng thái xử lý
  GET  /evidences/{id}/media     – danh sách file media
  POST /evidences/{id}/media     – upload file ảnh/video
  GET  /evidence-media/{id}/file – phát / tải file theo quyền
  DELETE /evidence-media/{id}    – xóa một file media
"""
from __future__ import annotations

import logging
import mimetypes
import os
import re
from datetime import datetime
from io import BytesIO
from pathlib import Path
from uuid import uuid4

from fastapi import APIRouter, Depends, File, HTTPException, Query, Response, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy import or_, select, func
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.audit import record_audit
from app.db import get_db
from app.dependencies import get_current_user, require_roles
from app.models import Alert, Artwork, Device, Evidence, EvidenceHistory, EvidenceMedia, Location, User
from app.schemas import EvidenceCreate, EvidenceDetail, EvidenceHistoryOut, EvidenceMediaOut, EvidenceOut, EvidenceStatusUpdate, Page

logger = logging.getLogger("artguard.evidence")

router = APIRouter(tags=["evidence"])

BACKEND_ROOT = Path(__file__).resolve().parents[2]
EVIDENCE_UPLOAD_DIR = BACKEND_ROOT / "uploads" / "evidence"

MAX_IMAGE_BYTES = 5 * 1024 * 1024        # 5 MB
MAX_VIDEO_BYTES = 100 * 1024 * 1024      # 100 MB

ALLOWED_IMAGE_MIME = {"image/jpeg", "image/png", "image/webp"}
ALLOWED_VIDEO_MIME = {"video/mp4", "video/webm", "video/ogg", "video/quicktime", "video/x-msvideo"}

# Tên file an toàn: UUID hex + extension cho phép
SAFE_EXTENSION_RE = re.compile(r"\.(jpg|jpeg|png|webp|mp4|webm|ogg|mov|avi)$", re.IGNORECASE)

mimetypes.add_type("video/mp4", ".mp4")
mimetypes.add_type("video/webm", ".webm")
mimetypes.add_type("image/jpeg", ".jpg")
mimetypes.add_type("image/webp", ".webp")


def _evidence_code() -> str:
    return f"EV-{uuid4().hex[:12].upper()}"


def _safe_subdir() -> Path:
    """Thư mục con theo năm/tháng để dễ quản lý."""
    now = datetime.utcnow()
    d = EVIDENCE_UPLOAD_DIR / f"{now.year:04d}" / f"{now.month:02d}"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _resolve_safe_path(relative: str) -> Path:
    """Giải quyết đường dẫn tương đối, chặn path traversal."""
    root = EVIDENCE_UPLOAD_DIR.resolve()
    candidate = (EVIDENCE_UPLOAD_DIR / relative).resolve()
    if not str(candidate).startswith(str(root)):
        raise HTTPException(400, "Đường dẫn file không hợp lệ")
    return candidate


def _evidence_out(ev: Evidence) -> EvidenceOut:
    has_image = any(m.media_type == "image" for m in ev.media)
    has_video = any(m.media_type == "video" for m in ev.media)
    return EvidenceOut(
        id=ev.id,
        evidence_code=ev.evidence_code,
        alert_id=ev.alert_id,
        device_id=ev.device_id,
        device_name=ev.device.name if ev.device else None,
        artwork_id=ev.artwork_id,
        artwork_title=ev.artwork.title if ev.artwork else None,
        location_id=ev.location_id,
        location_name=ev.location_name_snapshot or (ev.location.name if ev.location else None),
        event_type=ev.event_type,
        severity=ev.severity,
        processing_status=ev.processing_status,
        source=ev.source,
        confidence=ev.confidence,
        description=ev.description,
        detected_at=ev.detected_at,
        clip_start_at=ev.clip_start_at,
        clip_end_at=ev.clip_end_at,
        created_at=ev.created_at,
        updated_at=ev.updated_at,
        assigned_user_id=ev.assigned_user_id,
        has_image=has_image,
        has_video=has_video,
    )


def _evidence_detail(ev: Evidence) -> EvidenceDetail:
    out = _evidence_out(ev)
    media = [EvidenceMediaOut.model_validate(m) for m in ev.media]
    history = []
    for h in ev.history:
        history.append(EvidenceHistoryOut(
            id=h.id,
            from_status=h.from_status,
            to_status=h.to_status,
            note=h.note,
            changed_at=h.changed_at,
            user_name=h.user.full_name if h.user else None,
        ))
    return EvidenceDetail(**out.model_dump(), media=media, history=history)


# ── List ────────────────────────────────────────────────────────────────────

@router.get("/evidences", response_model=Page[EvidenceOut])
def list_evidences(
    q: str | None = None,
    severity: str | None = None,
    processing_status: str | None = None,
    source: str | None = None,
    device_id: int | None = None,
    artwork_id: int | None = None,
    location_id: int | None = None,
    alert_id: int | None = None,
    media_type: str | None = Query(None, pattern=r"^(image|video|both)$"),
    date_from: datetime | None = None,
    date_to: datetime | None = None,
    page_number: int = Query(1, alias="page", ge=1),
    page_size: int = Query(20, ge=1, le=100),
    _: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    stmt = select(Evidence)
    if q:
        needle = f"%{q.strip()}%"
        stmt = stmt.where(or_(
            Evidence.evidence_code.like(needle),
            Evidence.event_type.like(needle),
            Evidence.description.like(needle),
        ))
    if severity:
        stmt = stmt.where(Evidence.severity == severity)
    if processing_status:
        stmt = stmt.where(Evidence.processing_status == processing_status)
    if source:
        stmt = stmt.where(Evidence.source == source)
    if device_id:
        stmt = stmt.where(Evidence.device_id == device_id)
    if artwork_id:
        stmt = stmt.where(Evidence.artwork_id == artwork_id)
    if location_id:
        stmt = stmt.where(Evidence.location_id == location_id)
    if alert_id:
        stmt = stmt.where(Evidence.alert_id == alert_id)
    if date_from:
        stmt = stmt.where(Evidence.detected_at >= date_from)
    if date_to:
        stmt = stmt.where(Evidence.detected_at <= date_to)
    stmt = stmt.order_by(Evidence.detected_at.desc())

    total = db.scalar(select(func.count()).select_from(stmt.order_by(None).subquery())) or 0
    items = db.scalars(stmt.offset((page_number - 1) * page_size).limit(page_size)).all()
    return Page(items=[_evidence_out(ev) for ev in items], total=total, page=page_number, page_size=page_size)


# ── Create ──────────────────────────────────────────────────────────────────

@router.post("/evidences", response_model=EvidenceOut, status_code=201)
def create_evidence(
    payload: EvidenceCreate,
    user: User = Depends(require_roles("admin", "manager")),
    db: Session = Depends(get_db),
):
    # Snapshot location name tại thời điểm tạo
    location_name_snap: str | None = None
    if payload.location_id:
        loc = db.get(Location, payload.location_id)
        if loc:
            location_name_snap = loc.name

    ev = Evidence(
        evidence_code=_evidence_code(),
        location_name_snapshot=location_name_snap,
        **payload.model_dump(),
        created_at=datetime.utcnow(),
        updated_at=datetime.utcnow(),
    )
    db.add(ev)
    try:
        db.flush()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(409, "Mã bằng chứng bị trùng, thử lại.") from exc
    record_audit(db, user, "create", "evidence", ev.id, ev.evidence_code)
    db.commit()
    db.refresh(ev)
    return _evidence_out(ev)


# ── Get detail ──────────────────────────────────────────────────────────────

@router.get("/evidences/{evidence_id}", response_model=EvidenceDetail)
def get_evidence(
    evidence_id: int,
    _: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    ev = db.get(Evidence, evidence_id)
    if not ev:
        raise HTTPException(404, "Không tìm thấy bằng chứng")
    return _evidence_detail(ev)


# ── Update status ───────────────────────────────────────────────────────────

@router.patch("/evidences/{evidence_id}/status", response_model=EvidenceDetail)
def update_evidence_status(
    evidence_id: int,
    payload: EvidenceStatusUpdate,
    user: User = Depends(require_roles("admin", "manager", "operator")),
    db: Session = Depends(get_db),
):
    ev = db.get(Evidence, evidence_id)
    if not ev:
        raise HTTPException(404, "Không tìm thấy bằng chứng")
    old_status = ev.processing_status
    ev.processing_status = payload.processing_status
    ev.updated_at = datetime.utcnow()
    h = EvidenceHistory(
        evidence_id=ev.id,
        user_id=user.id,
        from_status=old_status,
        to_status=payload.processing_status,
        note=payload.note,
        changed_at=datetime.utcnow(),
    )
    db.add(h)
    record_audit(db, user, "update_status", "evidence", ev.id, payload.processing_status)
    db.commit()
    db.refresh(ev)
    return _evidence_detail(ev)


# ── Media list ──────────────────────────────────────────────────────────────

@router.get("/evidences/{evidence_id}/media", response_model=list[EvidenceMediaOut])
def list_evidence_media(
    evidence_id: int,
    _: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    ev = db.get(Evidence, evidence_id)
    if not ev:
        raise HTTPException(404, "Không tìm thấy bằng chứng")
    return [EvidenceMediaOut.model_validate(m) for m in ev.media]


# ── Upload media ─────────────────────────────────────────────────────────────

@router.post("/evidences/{evidence_id}/media", response_model=EvidenceMediaOut, status_code=201)
async def upload_evidence_media(
    evidence_id: int,
    file: UploadFile = File(...),
    user: User = Depends(require_roles("admin", "manager")),
    db: Session = Depends(get_db),
):
    ev = db.get(Evidence, evidence_id)
    if not ev:
        raise HTTPException(404, "Không tìm thấy bằng chứng")

    mime = file.content_type or ""
    is_image = mime in ALLOWED_IMAGE_MIME
    is_video = mime in ALLOWED_VIDEO_MIME

    if not is_image and not is_video:
        # Thử đoán từ tên file
        ext = Path(file.filename or "").suffix.lower() if file.filename else ""
        guessed = mimetypes.guess_type(f"f{ext}")[0] or ""
        is_image = guessed in ALLOWED_IMAGE_MIME
        is_video = guessed in ALLOWED_VIDEO_MIME
        if not is_image and not is_video:
            raise HTTPException(415, "Chỉ chấp nhận file ảnh (JPEG/PNG/WebP) hoặc video (MP4/WebM/OGG/MOV/AVI)")

    media_type = "image" if is_image else "video"
    max_size = MAX_IMAGE_BYTES if is_image else MAX_VIDEO_BYTES
    label = "5 MB" if is_image else "100 MB"

    data = await file.read(max_size + 1)
    if len(data) > max_size:
        raise HTTPException(413, f"Dung lượng tối đa cho {'ảnh' if is_image else 'video'} là {label}")

    # Kiểm tra magic bytes sơ lược
    if is_image and not _check_image_magic(data):
        raise HTTPException(415, "File không phải ảnh JPEG, PNG hoặc WebP hợp lệ")

    # Chặn file thực thi
    ext = SAFE_EXTENSION_RE.search(file.filename or "")
    if not ext:
        fallback_ext = ".jpg" if is_image else ".mp4"
    else:
        fallback_ext = ext.group(0).lower()
        if fallback_ext == ".jpeg":
            fallback_ext = ".jpg"

    filename = f"{uuid4().hex}{fallback_ext}"
    subdir = _safe_subdir()
    relative_path = str(subdir.relative_to(EVIDENCE_UPLOAD_DIR) / filename).replace("\\", "/")
    final_path = subdir / filename

    try:
        with final_path.open("xb") as f:
            f.write(data)
    except Exception:
        final_path.unlink(missing_ok=True)
        logger.exception("Evidence media upload failed for evidence %s", evidence_id)
        raise HTTPException(500, "Không thể lưu file. Thử lại sau.")

    media = EvidenceMedia(
        evidence_id=evidence_id,
        media_type=media_type,
        file_path=relative_path,
        file_size=len(data),
        mime_type=mime or mimetypes.guess_type(filename)[0],
        created_at=datetime.utcnow(),
    )
    db.add(media)
    ev.updated_at = datetime.utcnow()
    record_audit(db, user, "upload_media", "evidence", ev.id, filename)
    db.commit()
    db.refresh(media)
    return EvidenceMediaOut.model_validate(media)


# ── Serve / download file ───────────────────────────────────────────────────

@router.get("/evidence-media/{media_id}/file")
def serve_evidence_media(
    media_id: int,
    _: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    media = db.get(EvidenceMedia, media_id)
    if not media:
        raise HTTPException(404, "Không tìm thấy file")
    file_path = _resolve_safe_path(media.file_path)
    if not file_path.exists():
        raise HTTPException(404, "File không còn tồn tại trên hệ thống")
    return FileResponse(
        str(file_path),
        media_type=media.mime_type or "application/octet-stream",
        filename=file_path.name,
    )


# ── Delete media ─────────────────────────────────────────────────────────────

@router.delete("/evidence-media/{media_id}", status_code=204)
def delete_evidence_media(
    media_id: int,
    user: User = Depends(require_roles("admin", "manager")),
    db: Session = Depends(get_db),
):
    media = db.get(EvidenceMedia, media_id)
    if not media:
        raise HTTPException(404, "Không tìm thấy file")
    file_path = _resolve_safe_path(media.file_path)
    record_audit(db, user, "delete_media", "evidence", media.evidence_id, media.file_path)
    db.delete(media)
    db.commit()
    try:
        file_path.unlink(missing_ok=True)
    except OSError:
        logger.warning("Could not remove evidence media file %s", file_path)
    return Response(status_code=204)


# ── Alerts linked to an evidence ─────────────────────────────────────────────

@router.get("/alerts/{alert_id}/evidences", response_model=list[EvidenceOut])
def alert_evidences(
    alert_id: int,
    _: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if not db.get(Alert, alert_id):
        raise HTTPException(404, "Không tìm thấy cảnh báo")
    rows = db.scalars(
        select(Evidence).where(Evidence.alert_id == alert_id).order_by(Evidence.detected_at.desc())
    ).all()
    return [_evidence_out(ev) for ev in rows]


# ── Helpers ──────────────────────────────────────────────────────────────────

def _check_image_magic(data: bytes) -> bool:
    """Kiểm tra magic bytes đơn giản cho JPEG, PNG, WebP."""
    if data[:3] == b"\xff\xd8\xff":
        return True  # JPEG
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return True  # PNG
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return True  # WebP
    return False
