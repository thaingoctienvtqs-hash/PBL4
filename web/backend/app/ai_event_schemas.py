"""Versioned AI producer contract, independent of the human Evidence API."""
from datetime import datetime, timezone
import math
from typing import Literal
from uuid import UUID
from pydantic import BaseModel, ConfigDict, Field, StrictStr, field_validator

class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")

class Scores(StrictModel):
    object_contact: float | None = Field(default=None, ge=0, le=1)

    @field_validator("object_contact", mode="before")
    @classmethod
    def finite_score(cls, value):
        if value is not None and (isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value)):
            raise ValueError("Object-Contact must be a finite numeric score")
        return value

class EvidenceReference(StrictModel):
    status: Literal["PENDING"] = "PENDING"

class AiEventIn(StrictModel):
    schema_version: Literal["1"]
    event_id: UUID
    producer_id: StrictStr = Field(min_length=1, max_length=80, pattern=r"^[a-z0-9][a-z0-9_-]*$")
    producer_instance_id: UUID
    source_event_id: StrictStr = Field(min_length=1, max_length=80)
    data_origin: Literal["SYNTHETIC_TEST", "REAL_AI"]
    event_type: Literal["AI_CONTACT_SUSPECTED_IN_ROI"]
    detected_at: datetime
    time_source: Literal["ALERT_DECISION", "EVENTSTORE_RECORD"] = "ALERT_DECISION"
    artwork_id: int | None = Field(default=None, gt=0)
    device_id: int | None = Field(default=None, gt=0)
    scores: Scores = Field(default_factory=Scores)
    evidence_ref: EvidenceReference | None = None

    @field_validator("detected_at")
    @classmethod
    def aware_utc(cls, value):
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("detected_at must have a timezone")
        return value.astimezone(timezone.utc)

    @field_validator("artwork_id", "device_id", mode="before")
    @classmethod
    def strict_identifier(cls, value):
        if value is not None and type(value) is not int:
            raise ValueError("Mapping identifiers must be integers")
        return value

class AiEventAck(StrictModel):
    schema_version: Literal["1"] = "1"
    event_id: UUID
    producer_id: str
    receipt_id: int
    alert_id: int
    evidence_id: int
    data_origin: Literal["SYNTHETIC_TEST", "REAL_AI"]
    replayed: bool
    evidence_status: Literal["PENDING", "READY", "MISSING"]

class MediaAck(StrictModel):
    event_id: UUID
    producer_id: str
    receipt_id: int
    alert_id: int
    evidence_id: int
    media_id: int
    evidence_status: Literal["READY"]
    replayed: bool
