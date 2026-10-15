from datetime import datetime
from typing import Generic, TypeVar

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator

T = TypeVar("T")


class Page(BaseModel, Generic[T]):
    items: list[T]
    total: int
    page: int
    page_size: int


class LoginRequest(BaseModel):
    username: str = Field(min_length=1, max_length=80)
    password: str = Field(min_length=1, max_length=128)


class UserOut(BaseModel):
    id: int
    username: str
    email: EmailStr
    full_name: str
    is_active: bool
    roles: list[str]
    created_at: datetime


class LoginResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int
    user: UserOut


class UserCreate(BaseModel):
    username: str = Field(min_length=3, max_length=80, pattern=r"^[a-zA-Z0-9_.-]+$")
    email: EmailStr
    full_name: str = Field(min_length=2, max_length=160)
    password: str = Field(min_length=10, max_length=128)
    roles: list[str] = Field(min_length=1)


class UserUpdate(BaseModel):
    email: EmailStr | None = None
    full_name: str | None = Field(default=None, min_length=2, max_length=160)
    roles: list[str] | None = Field(default=None, min_length=1)
    is_active: bool | None = None


class LocationCreate(BaseModel):
    code: str = Field(min_length=2, max_length=32, pattern=r"^[A-Za-z0-9_-]+$")
    name: str = Field(min_length=2, max_length=120)
    description: str | None = None
    capacity: int | None = Field(default=None, ge=1, le=100000)
    is_active: bool = True


class LocationUpdate(BaseModel):
    code: str | None = Field(default=None, min_length=2, max_length=32, pattern=r"^[A-Za-z0-9_-]+$")
    name: str | None = Field(default=None, min_length=2, max_length=120)
    description: str | None = None
    capacity: int | None = Field(default=None, ge=1, le=100000)
    is_active: bool | None = None


class LocationOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    code: str
    name: str
    description: str | None
    capacity: int | None
    is_active: bool
    created_at: datetime
    updated_at: datetime


class ArtworkCreate(BaseModel):
    inventory_code: str = Field(min_length=2, max_length=40, pattern=r"^[A-Za-z0-9_-]+$")
    title: str = Field(min_length=1, max_length=180)
    artist: str = Field(min_length=1, max_length=160)
    year_created: int | None = Field(default=None, ge=0, le=2100)
    medium: str | None = Field(default=None, max_length=120)
    description: str | None = None
    image_url: str | None = Field(default=None, max_length=500)
    status: str = Field(default="displayed", pattern=r"^(displayed|in_storage|under_review)$")
    location_id: int | None = None


class ArtworkUpdate(BaseModel):
    inventory_code: str | None = Field(default=None, min_length=2, max_length=40, pattern=r"^[A-Za-z0-9_-]+$")
    title: str | None = Field(default=None, min_length=1, max_length=180)
    artist: str | None = Field(default=None, min_length=1, max_length=160)
    year_created: int | None = Field(default=None, ge=0, le=2100)
    medium: str | None = Field(default=None, max_length=120)
    description: str | None = None
    image_url: str | None = Field(default=None, max_length=500)
    status: str | None = Field(default=None, pattern=r"^(displayed|in_storage|under_review)$")
    location_id: int | None = None


class ArtworkOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    inventory_code: str
    title: str
    artist: str
    year_created: int | None
    medium: str | None
    description: str | None
    image_url: str | None
    status: str
    location_id: int | None
    location_name: str | None = None
    created_at: datetime
    updated_at: datetime


class DeviceCreate(BaseModel):
    device_code: str = Field(min_length=2, max_length=40, pattern=r"^[A-Za-z0-9_-]+$")
    name: str = Field(min_length=2, max_length=140)
    device_type: str = Field(default="simulated_camera", max_length=48)
    status: str = Field(default="online", pattern=r"^(online|offline|maintenance)$")
    location_id: int | None = None
    artwork_id: int | None = None
    notes: str | None = None


class DeviceUpdate(BaseModel):
    device_code: str | None = Field(default=None, min_length=2, max_length=40, pattern=r"^[A-Za-z0-9_-]+$")
    name: str | None = Field(default=None, min_length=2, max_length=140)
    device_type: str | None = Field(default=None, max_length=48)
    status: str | None = Field(default=None, pattern=r"^(online|offline|maintenance)$")
    location_id: int | None = None
    artwork_id: int | None = None
    notes: str | None = None


class DeviceOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    device_code: str
    name: str
    device_type: str
    status: str
    location_id: int | None
    location_name: str | None = None
    artwork_id: int | None
    artwork_title: str | None = None
    last_seen_at: datetime | None
    notes: str | None
    stream_url: str | None = None
    stream_type: str | None = None
    created_at: datetime
    updated_at: datetime


class AlertCreate(BaseModel):
    title: str = Field(min_length=3, max_length=180)
    description: str = Field(min_length=3)
    severity: str = Field(pattern=r"^(low|medium|high|critical)$")
    artwork_id: int | None = None
    device_id: int | None = None


class AlertStatusUpdate(BaseModel):
    status: str = Field(pattern=r"^(acknowledged|investigating|resolved|false_positive)$")
    note: str | None = Field(default=None, max_length=500)


class AlertNoteCreate(BaseModel):
    content: str = Field(min_length=1, max_length=4000)


class AlertOut(BaseModel):
    id: int
    event_code: str
    title: str
    description: str
    severity: str
    status: str
    source: str
    detected_at: datetime
    resolved_at: datetime | None
    artwork_id: int | None
    artwork_title: str | None
    device_id: int | None
    device_name: str | None
    assigned_user_id: int | None


class AlertNoteOut(BaseModel):
    id: int
    content: str
    created_at: datetime
    user_name: str


class AlertHistoryOut(BaseModel):
    id: int
    from_status: str | None
    to_status: str
    note: str | None
    changed_at: datetime
    user_name: str | None


class SettingUpdate(BaseModel):
    value: str = Field(max_length=4000)


class ModelVersionCreate(BaseModel):
    name: str = Field(min_length=2, max_length=100)
    version: str = Field(min_length=1, max_length=40)
    notes: str | None = None


class SettingOut(BaseModel):
    key: str
    value: str
    updated_at: datetime


# ── Device stream config ────────────────────────────────────────────────────

STREAM_TYPE_VALUES = {"mjpeg", "hls", "mp4", "rtsp"}


class DeviceStreamUpdate(BaseModel):
    stream_url: str | None = Field(default=None, max_length=500)
    stream_type: str | None = Field(default=None, pattern=r"^(mjpeg|hls|mp4|rtsp)$")


class DeviceOutWithStream(DeviceOut):
    stream_url: str | None = None
    stream_type: str | None = None


# ── Evidence schemas ────────────────────────────────────────────────────────

class EvidenceMediaOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    media_type: str
    file_path: str
    file_size: int | None
    mime_type: str | None
    thumbnail_path: str | None
    media_timestamp: datetime | None
    duration_seconds: float | None
    created_at: datetime


class EvidenceOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    evidence_code: str
    alert_id: int | None
    device_id: int | None
    device_name: str | None = None
    artwork_id: int | None
    artwork_title: str | None = None
    location_id: int | None
    location_name: str | None = None
    event_type: str
    severity: str
    processing_status: str
    source: str
    confidence: float | None
    description: str | None
    detected_at: datetime
    clip_start_at: datetime | None
    clip_end_at: datetime | None
    created_at: datetime
    updated_at: datetime
    assigned_user_id: int | None
    has_image: bool = False
    has_video: bool = False


class EvidenceDetail(EvidenceOut):
    media: list[EvidenceMediaOut] = []
    history: list["EvidenceHistoryOut"] = []


class EvidenceCreate(BaseModel):
    event_type: str = Field(min_length=2, max_length=48)
    severity: str = Field(pattern=r"^(low|medium|high|critical)$")
    source: str = Field(default="demo", pattern=r"^(demo|ai|manual)$")
    description: str | None = Field(default=None, max_length=4000)
    detected_at: datetime
    clip_start_at: datetime | None = None
    clip_end_at: datetime | None = None
    alert_id: int | None = None
    device_id: int | None = None
    artwork_id: int | None = None
    location_id: int | None = None
    assigned_user_id: int | None = None


class EvidenceStatusUpdate(BaseModel):
    processing_status: str = Field(pattern=r"^(reviewed|resolved|dismissed)$")
    note: str | None = Field(default=None, max_length=500)


class EvidenceHistoryOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    from_status: str | None
    to_status: str
    note: str | None
    changed_at: datetime
    user_name: str | None = None

