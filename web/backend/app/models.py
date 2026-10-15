from datetime import datetime

from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Index, Integer, Table, Unicode, UnicodeText, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base

LongUnicodeText = UnicodeText().with_variant(Unicode(), "mssql")

user_roles = Table(
    "user_roles", Base.metadata,
    Column("user_id", ForeignKey("users.id", ondelete="CASCADE"), primary_key=True),
    Column("role_id", ForeignKey("roles.id", ondelete="CASCADE"), primary_key=True),
)


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)


class Role(Base):
    __tablename__ = "roles"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(Unicode(32), unique=True, nullable=False)
    users: Mapped[list["User"]] = relationship(secondary=user_roles, back_populates="roles")


class User(TimestampMixin, Base):
    __tablename__ = "users"
    __table_args__ = (Index("ix_users_active_username", "is_active", "username"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    username: Mapped[str] = mapped_column(Unicode(80), unique=True, nullable=False)
    email: Mapped[str] = mapped_column(Unicode(255), unique=True, nullable=False)
    full_name: Mapped[str] = mapped_column(Unicode(160), nullable=False)
    password_hash: Mapped[str] = mapped_column(Unicode(255), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    roles: Mapped[list[Role]] = relationship(secondary=user_roles, back_populates="users", lazy="selectin")


class Location(TimestampMixin, Base):
    __tablename__ = "locations"
    __table_args__ = (Index("ix_locations_active_name", "is_active", "name"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(Unicode(32), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(Unicode(120), nullable=False)
    description: Mapped[str | None] = mapped_column(LongUnicodeText)
    capacity: Mapped[int | None] = mapped_column(Integer)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    artworks: Mapped[list["Artwork"]] = relationship(back_populates="location")
    devices: Mapped[list["Device"]] = relationship(back_populates="location")


class Artwork(TimestampMixin, Base):
    __tablename__ = "artworks"
    __table_args__ = (Index("ix_artworks_location_status", "location_id", "status"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    inventory_code: Mapped[str] = mapped_column(Unicode(40), unique=True, nullable=False)
    title: Mapped[str] = mapped_column(Unicode(180), nullable=False)
    artist: Mapped[str] = mapped_column(Unicode(160), nullable=False)
    year_created: Mapped[int | None] = mapped_column(Integer)
    medium: Mapped[str | None] = mapped_column(Unicode(120))
    description: Mapped[str | None] = mapped_column(LongUnicodeText)
    image_url: Mapped[str | None] = mapped_column(Unicode(500))
    status: Mapped[str] = mapped_column(Unicode(24), default="displayed", nullable=False)
    location_id: Mapped[int | None] = mapped_column(ForeignKey("locations.id", ondelete="SET NULL"))
    location: Mapped[Location | None] = relationship(back_populates="artworks")


class Device(TimestampMixin, Base):
    __tablename__ = "devices"
    __table_args__ = (Index("ix_devices_location_status", "location_id", "status"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    device_code: Mapped[str] = mapped_column(Unicode(40), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(Unicode(140), nullable=False)
    device_type: Mapped[str] = mapped_column(Unicode(48), default="simulated_camera", nullable=False)
    status: Mapped[str] = mapped_column(Unicode(24), default="online", nullable=False)
    location_id: Mapped[int | None] = mapped_column(ForeignKey("locations.id", ondelete="SET NULL"))
    artwork_id: Mapped[int | None] = mapped_column(ForeignKey("artworks.id", ondelete="SET NULL"))
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime)
    notes: Mapped[str | None] = mapped_column(LongUnicodeText)
    # Camera stream configuration (None = not configured / demo mode)
    stream_url: Mapped[str | None] = mapped_column(Unicode(500))
    stream_type: Mapped[str | None] = mapped_column(Unicode(24))  # mjpeg | hls | mp4 | rtsp
    location: Mapped[Location | None] = relationship(back_populates="devices")
    artwork: Mapped[Artwork | None] = relationship()


class Alert(Base):
    __tablename__ = "alerts"
    __table_args__ = (Index("ix_alerts_status_severity_time", "status", "severity", "detected_at"), Index("ix_alerts_artwork_time", "artwork_id", "detected_at"))
    id: Mapped[int] = mapped_column(primary_key=True)
    event_code: Mapped[str] = mapped_column(Unicode(48), unique=True, nullable=False)
    title: Mapped[str] = mapped_column(Unicode(180), nullable=False)
    description: Mapped[str] = mapped_column(LongUnicodeText, nullable=False)
    severity: Mapped[str] = mapped_column(Unicode(16), nullable=False)
    status: Mapped[str] = mapped_column(Unicode(24), default="new", nullable=False)
    source: Mapped[str] = mapped_column(Unicode(24), default="demo", nullable=False)
    detected_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, index=True)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime)
    artwork_id: Mapped[int | None] = mapped_column(ForeignKey("artworks.id", ondelete="SET NULL"))
    device_id: Mapped[int | None] = mapped_column(ForeignKey("devices.id", ondelete="SET NULL"))
    assigned_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    artwork: Mapped[Artwork | None] = relationship()
    device: Mapped[Device | None] = relationship()
    assigned_user: Mapped[User | None] = relationship()
    notes: Mapped[list["AlertNote"]] = relationship(back_populates="alert", cascade="all, delete-orphan", order_by="AlertNote.created_at.desc()")
    history: Mapped[list["AlertHistory"]] = relationship(back_populates="alert", cascade="all, delete-orphan", order_by="AlertHistory.changed_at.desc()")


class AlertNote(Base):
    __tablename__ = "alert_notes"
    id: Mapped[int] = mapped_column(primary_key=True)
    alert_id: Mapped[int] = mapped_column(ForeignKey("alerts.id", ondelete="CASCADE"), nullable=False, index=True)
    # SQL Server supports NO ACTION (RESTRICT is not valid T-SQL).
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="NO ACTION"), nullable=False)
    content: Mapped[str] = mapped_column(LongUnicodeText, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
    alert: Mapped[Alert] = relationship(back_populates="notes")
    user: Mapped[User] = relationship()


class AlertHistory(Base):
    __tablename__ = "alert_history"
    id: Mapped[int] = mapped_column(primary_key=True)
    alert_id: Mapped[int] = mapped_column(ForeignKey("alerts.id", ondelete="CASCADE"), nullable=False, index=True)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    from_status: Mapped[str | None] = mapped_column(Unicode(24))
    to_status: Mapped[str] = mapped_column(Unicode(24), nullable=False)
    note: Mapped[str | None] = mapped_column(Unicode(500))
    changed_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
    alert: Mapped[Alert] = relationship(back_populates="history")
    user: Mapped[User | None] = relationship()


class ModelVersion(Base):
    __tablename__ = "model_versions"
    __table_args__ = (UniqueConstraint("name", "version", name="uq_model_name_version"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(Unicode(100), nullable=False)
    version: Mapped[str] = mapped_column(Unicode(40), nullable=False)
    status: Mapped[str] = mapped_column(Unicode(24), default="demo", nullable=False)
    is_demo: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    notes: Mapped[str | None] = mapped_column(LongUnicodeText)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)


class SystemSetting(Base):
    __tablename__ = "system_settings"
    key: Mapped[str] = mapped_column(Unicode(80), primary_key=True)
    value: Mapped[str] = mapped_column(LongUnicodeText, nullable=False)
    updated_by: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)


class AuditLog(Base):
    __tablename__ = "audit_logs"
    __table_args__ = (Index("ix_audit_entity_created", "entity_type", "entity_id", "created_at"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    action: Mapped[str] = mapped_column(Unicode(80), nullable=False)
    entity_type: Mapped[str] = mapped_column(Unicode(48), nullable=False)
    entity_id: Mapped[int | None] = mapped_column(Integer)
    result: Mapped[str] = mapped_column(Unicode(24), default="success", nullable=False)
    detail: Mapped[str | None] = mapped_column(LongUnicodeText)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False, index=True)
    user: Mapped[User | None] = relationship()


class DeviceStatusHistory(Base):
    __tablename__ = "device_status_history"
    id: Mapped[int] = mapped_column(primary_key=True)
    device_id: Mapped[int] = mapped_column(ForeignKey("devices.id", ondelete="CASCADE"), nullable=False, index=True)
    status: Mapped[str] = mapped_column(Unicode(24), nullable=False)
    recorded_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
    device: Mapped[Device] = relationship()


class Evidence(Base):
    """Bằng chứng vi phạm: ảnh/video được ghi lại liên quan đến một sự kiện."""
    __tablename__ = "evidences"
    __table_args__ = (
        Index("ix_evidences_detected_at", "detected_at"),
        Index("ix_evidences_device_time", "device_id", "detected_at"),
        Index("ix_evidences_artwork_time", "artwork_id", "detected_at"),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    evidence_code: Mapped[str] = mapped_column(Unicode(48), unique=True, nullable=False)
    # Liên kết (tuỳ chọn)
    alert_id: Mapped[int | None] = mapped_column(ForeignKey("alerts.id", ondelete="SET NULL"))
    device_id: Mapped[int | None] = mapped_column(ForeignKey("devices.id", ondelete="SET NULL"))
    artwork_id: Mapped[int | None] = mapped_column(ForeignKey("artworks.id", ondelete="SET NULL"))
    location_id: Mapped[int | None] = mapped_column(ForeignKey("locations.id", ondelete="SET NULL"))
    # Snapshot metadata khu vực tại thời điểm ghi (để bảo toàn tracability khi config thay đổi)
    location_name_snapshot: Mapped[str | None] = mapped_column(Unicode(120))
    # Phân loại sự kiện
    event_type: Mapped[str] = mapped_column(Unicode(48), nullable=False)  # proximity|touching|suspicious_behavior|...
    severity: Mapped[str] = mapped_column(Unicode(16), nullable=False, default="medium")  # low|medium|high|critical
    processing_status: Mapped[str] = mapped_column(Unicode(24), default="pending", nullable=False)  # pending|reviewed|resolved|dismissed
    # Nguồn ghi nhận: demo | ai | manual
    source: Mapped[str] = mapped_column(Unicode(24), default="demo", nullable=False)
    # Tin cậy model (nếu có; NULL nếu không phải AI thật)
    confidence: Mapped[float | None] = mapped_column()
    # Mô tả
    description: Mapped[str | None] = mapped_column(LongUnicodeText)
    # Thời gian (UTC)
    detected_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    clip_start_at: Mapped[datetime | None] = mapped_column(DateTime)
    clip_end_at: Mapped[datetime | None] = mapped_column(DateTime)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)
    # Người phụ trách
    assigned_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    # Relationships
    alert: Mapped["Alert | None"] = relationship()
    device: Mapped[Device | None] = relationship()
    artwork: Mapped[Artwork | None] = relationship()
    location: Mapped[Location | None] = relationship()
    assigned_user: Mapped[User | None] = relationship()
    media: Mapped[list["EvidenceMedia"]] = relationship(back_populates="evidence", cascade="all, delete-orphan", order_by="EvidenceMedia.created_at")


class EvidenceMedia(Base):
    """File media (ảnh hoặc video) thuộc một bằng chứng."""
    __tablename__ = "evidence_media"
    id: Mapped[int] = mapped_column(primary_key=True)
    evidence_id: Mapped[int] = mapped_column(ForeignKey("evidences.id", ondelete="CASCADE"), nullable=False, index=True)
    media_type: Mapped[str] = mapped_column(Unicode(8), nullable=False)  # image | video
    file_path: Mapped[str] = mapped_column(Unicode(500), nullable=False)  # relative path từ uploads/
    file_size: Mapped[int | None] = mapped_column(Integer)   # bytes
    mime_type: Mapped[str | None] = mapped_column(Unicode(64))
    thumbnail_path: Mapped[str | None] = mapped_column(Unicode(500))
    # Thời gian thực trong media (nếu biết; phân biệt với thời gian upload)
    media_timestamp: Mapped[datetime | None] = mapped_column(DateTime)
    duration_seconds: Mapped[float | None] = mapped_column()
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
    evidence: Mapped[Evidence] = relationship(back_populates="media")


class EvidenceHistory(Base):
    """Lịch sử cập nhật trạng thái xử lý bằng chứng."""
    __tablename__ = "evidence_history"
    id: Mapped[int] = mapped_column(primary_key=True)
    evidence_id: Mapped[int] = mapped_column(ForeignKey("evidences.id", ondelete="CASCADE"), nullable=False, index=True)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    from_status: Mapped[str | None] = mapped_column(Unicode(24))
    to_status: Mapped[str] = mapped_column(Unicode(24), nullable=False)
    note: Mapped[str | None] = mapped_column(Unicode(500))
    changed_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
    evidence: Mapped[Evidence] = relationship()
    user: Mapped[User | None] = relationship()
