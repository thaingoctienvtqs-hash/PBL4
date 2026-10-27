"""Integration-only receipt tables, registered explicitly by the TEST factory."""
from datetime import datetime
from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, Integer, Unicode, UnicodeText, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column
from app.db import Base

_TEXT = UnicodeText().with_variant(Unicode(), "mssql")

class AiEventReceipt(Base):
    __tablename__ = "ai_event_receipts"
    __table_args__ = (
        UniqueConstraint("producer_id", "event_id", name="uq_ai_event_producer_event"),
        CheckConstraint("data_origin IN ('SYNTHETIC_TEST','REAL_AI')", name="ck_ai_event_origin"),
        Index("ix_ai_event_alert", "alert_id"),
        Index("ix_ai_event_received", "received_at"),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    producer_id: Mapped[str] = mapped_column(Unicode(80), nullable=False)
    event_id: Mapped[str] = mapped_column(Unicode(36), nullable=False)
    producer_instance_id: Mapped[str] = mapped_column(Unicode(36), nullable=False)
    source_event_id: Mapped[str] = mapped_column(Unicode(80), nullable=False)
    schema_version: Mapped[str] = mapped_column(Unicode(8), nullable=False)
    data_origin: Mapped[str] = mapped_column(Unicode(24), nullable=False)
    event_type: Mapped[str] = mapped_column(Unicode(48), nullable=False)
    detected_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    received_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    payload_sha256: Mapped[str] = mapped_column(Unicode(64), nullable=False)
    payload_json: Mapped[str] = mapped_column(_TEXT, nullable=False)
    # NO ACTION avoids extra SQL Server cascade paths; ingest data is retained.
    alert_id: Mapped[int | None] = mapped_column(ForeignKey("alerts.id", ondelete="NO ACTION"))
    evidence_id: Mapped[int | None] = mapped_column(ForeignKey("evidences.id", ondelete="NO ACTION"))

class AiEventAttachment(Base):
    __tablename__ = "ai_event_attachments"
    receipt_id: Mapped[int] = mapped_column(
        ForeignKey("ai_event_receipts.id", ondelete="NO ACTION"), primary_key=True)
    sha256: Mapped[str] = mapped_column(Unicode(64), nullable=False)
    byte_length: Mapped[int] = mapped_column(Integer, nullable=False)
    # Deliberate logical media reference: retained receipt can report MISSING
    # if an operator removes media through the existing protected API.
    media_id: Mapped[int | None] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
