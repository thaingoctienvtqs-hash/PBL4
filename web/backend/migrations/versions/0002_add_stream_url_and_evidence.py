"""Add stream_url to devices and create evidence tables.

Revision ID: 0002_add_stream_url_and_evidence
Revises: 0001_initial_schema
Create Date: 2026-10-14
"""
from alembic import op
import sqlalchemy as sa

revision = "0002_add_stream_url_and_evidence"
down_revision = "0001_initial_schema"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()

    inspector = sa.inspect(bind)
    existing_tables = inspector.get_table_names()

    # --- devices: thêm stream_url, stream_type nếu chưa có ---
    if "devices" in existing_tables:
        existing_cols = {col["name"] for col in inspector.get_columns("devices")}
        if "stream_url" not in existing_cols:
            op.add_column("devices", sa.Column("stream_url", sa.Unicode(500), nullable=True))
        if "stream_type" not in existing_cols:
            op.add_column("devices", sa.Column("stream_type", sa.Unicode(24), nullable=True))

    # --- evidences ---
    if "evidences" not in existing_tables:
        op.create_table(
            "evidences",
            sa.Column("id", sa.Integer, primary_key=True),
            sa.Column("evidence_code", sa.Unicode(48), nullable=False, unique=True),
            sa.Column("alert_id", sa.Integer, sa.ForeignKey("alerts.id", ondelete="SET NULL"), nullable=True),
            sa.Column("device_id", sa.Integer, sa.ForeignKey("devices.id", ondelete="SET NULL"), nullable=True),
            sa.Column("artwork_id", sa.Integer, sa.ForeignKey("artworks.id", ondelete="SET NULL"), nullable=True),
            sa.Column("location_id", sa.Integer, sa.ForeignKey("locations.id", ondelete="SET NULL"), nullable=True),
            sa.Column("location_name_snapshot", sa.Unicode(120), nullable=True),
            sa.Column("event_type", sa.Unicode(48), nullable=False),
            sa.Column("severity", sa.Unicode(16), nullable=False, server_default="medium"),
            sa.Column("processing_status", sa.Unicode(24), nullable=False, server_default="pending"),
            sa.Column("source", sa.Unicode(24), nullable=False, server_default="demo"),
            sa.Column("confidence", sa.Float, nullable=True),
            sa.Column("description", sa.UnicodeText, nullable=True),
            sa.Column("detected_at", sa.DateTime, nullable=False),
            sa.Column("clip_start_at", sa.DateTime, nullable=True),
            sa.Column("clip_end_at", sa.DateTime, nullable=True),
            sa.Column("created_at", sa.DateTime, nullable=False),
            sa.Column("updated_at", sa.DateTime, nullable=False),
            sa.Column("assigned_user_id", sa.Integer, sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        )
        op.create_index("ix_evidences_detected_at", "evidences", ["detected_at"])
        op.create_index("ix_evidences_device_time", "evidences", ["device_id", "detected_at"])
        op.create_index("ix_evidences_artwork_time", "evidences", ["artwork_id", "detected_at"])

    # --- evidence_media ---
    if "evidence_media" not in existing_tables:
        op.create_table(
            "evidence_media",
            sa.Column("id", sa.Integer, primary_key=True),
            sa.Column("evidence_id", sa.Integer, sa.ForeignKey("evidences.id", ondelete="CASCADE"), nullable=False),
            sa.Column("media_type", sa.Unicode(8), nullable=False),
            sa.Column("file_path", sa.Unicode(500), nullable=False),
            sa.Column("file_size", sa.Integer, nullable=True),
            sa.Column("mime_type", sa.Unicode(64), nullable=True),
            sa.Column("thumbnail_path", sa.Unicode(500), nullable=True),
            sa.Column("media_timestamp", sa.DateTime, nullable=True),
            sa.Column("duration_seconds", sa.Float, nullable=True),
            sa.Column("created_at", sa.DateTime, nullable=False),
        )
        op.create_index("ix_evidence_media_evidence_id", "evidence_media", ["evidence_id"])

    # --- evidence_history ---
    if "evidence_history" not in existing_tables:
        op.create_table(
            "evidence_history",
            sa.Column("id", sa.Integer, primary_key=True),
            sa.Column("evidence_id", sa.Integer, sa.ForeignKey("evidences.id", ondelete="CASCADE"), nullable=False),
            sa.Column("user_id", sa.Integer, sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
            sa.Column("from_status", sa.Unicode(24), nullable=True),
            sa.Column("to_status", sa.Unicode(24), nullable=False),
            sa.Column("note", sa.Unicode(500), nullable=True),
            sa.Column("changed_at", sa.DateTime, nullable=False),
        )
        op.create_index("ix_evidence_history_evidence_id", "evidence_history", ["evidence_id"])


def downgrade() -> None:
    # Non-destructive: không xóa bảng hoặc cột khi downgrade.
    pass
